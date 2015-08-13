import logging
import re
import psycopg2
import csv

from dipper.sources.Source import Source
from dipper.models.assoc.Association import Assoc
from dipper.models.Dataset import Dataset
from dipper.models.assoc.G2PAssoc import G2PAssoc
from dipper.models.Genotype import Genotype
from dipper.models.Reference import Reference
from dipper.models.Environment import Environment
from dipper import config
from dipper import curie_map
from dipper.utils.GraphUtils import GraphUtils
from dipper.models.GenomicFeature import Feature, makeChromID


logger = logging.getLogger(__name__)


class FlyBase(Source):
    """
    This is the [Drosophila Genetics](http://www.flybase.org/) resource,
    from which we process genotype and phenotype data about fruitfly.
    Genotypes leverage the GENO genotype model.

    Here, we connect to their public database, and download a subset of tables/views to get specifically at the
    geno-pheno data, then iterate over the tables.  We end up effectively performing joins when adding nodes
    to the graph.
    We connect using the [Direct Chado Access](http://gmod.org/wiki/Public_Chado_Databases#Direct_Chado_Access)

    """


    tables = [
        'genotype',  # done
        'feature_genotype',
        'pub',  # done
        'feature_pub',  # done
        'pub_dbxref',
        # 'feature_dbxref',
        # 'feature_relationship',
        # 'cvterm',
        'stock_genotype',
        'stock',
        'organism',  # may not be necessary
        'environment',   # done
        # 'phenotype',  UNFINISHED
        'phenstatement',
        # 'dbxref',
        # 'db',
        'phenotype_cvterm',
        'phendesc',
        # 'strain',
        # 'environment_cvterm',
    ]

    def __init__(self):
        Source.__init__(self, 'flybase')
        self.namespaces.update(curie_map.get())

        # update the dataset object with details about this resource
        self.dataset = Dataset('flybase', 'FlyBase', 'http://www.flybase.org/', None,
                               None, 'http://flybase.org/wiki/FlyBase:FilesOverview')

        # check if config exists; if it doesn't, error out and let user know
        if 'dbauth' not in config.get_config() and 'mgi' not in config.get_config()['dbauth']:
            logger.error("not configured with PG user/password.")

        # source-specific warnings.  will be cleared when resolved.
        logger.warn("we are ignoring normal phenotypes for now")

        # so that we don't have to deal with BNodes, we will create hash lookups for the internal identifiers
        # the hash will hold the type-specific-object-keys to FB public identifiers.  then, subsequent
        # views of the table will lookup the identifiers in the hash.  this allows us to do the 'joining' on the
        # fly
        self.idhash = {'allele': {}, 'marker': {}, 'publication': {}, 'stock': {},
                       'genotype': {}, 'annot': {}, 'notes': {}, 'organism': {},
                       'environment': {}, 'feature': {}, 'phenotype': {}, 'cvterm': {}}
        self.dbxrefs = {}
        self.markers = {'classes': [], 'indiv': []}  # to store if a marker is a class or indiv

        self.label_hash = {}  # use this to store internally generated labels for various features
        self.geno_bkgd = {}  # use this to store the genotype strain ids for building genotype labels
        self.phenocv = {}  # mappings between internal phenotype db key and multiple cv terms

        return

    def fetch(self, is_dl_forced=False):
        """
        For the MGI resource, we connect to the remote database, and pull the tables into local files.
        We'll check the local table versions against the remote version
        :return:
        """

        # create the connection details for MGI
        cxn = {'host': 'flybase.org', 'database': 'flybase', 'port': 5432, 'user': 'flybase',
               'password': 'no password'}

        self.dataset.setFileAccessUrl(''.join(('jdbc:postgresql://', cxn['host'], ':',
                                               str(cxn['port']), '/', cxn['database'])))

        # process the tables
        # self.fetch_from_pgdb(self.tables,cxn,100)  #for testing
        # self.fetch_from_pgdb(self.tables, cxn, None, is_dl_forced)


        # we want to fetch the features, but just a subset to reduce the processing time
        query = "select feature_id, dbxref_id, organism_id, name, uniquename, null as residues,"\
                +"seqlen, md5checksum, type_id, is_analysis, timeaccessioned, timelastmodified, is_obsolete "\
                +"from feature where is_analysis = false"

        self.fetch_query_from_pgdb('feature', query, None, cxn, None, is_dl_forced)

        return

    def parse(self, limit=None):
        """
        We process each of the postgres tables in turn.  The order of processing is important here, as we build
        up a hashmap of internal vs external identifers (unique keys by type to FB id).  These include
        allele, marker (gene), publication, strain, genotype, annotation (association), and descriptive notes.
        :param limit: Only parse this many lines of each table
        :return:
        """
        if limit is not None:
            logger.info("Only parsing first %d rows of each file", limit)
        logger.info("Parsing files...")

        if self.testOnly:
            self.testMode = True

        self.nobnodes = True

        # the following will provide us the hash-lookups
        self._process_dbxref()
        self._process_cvterm()
        self._process_genotypes(limit)
        # self._process_stocks(limit)
        self._process_pubs(limit)
        self._process_environments(limit)
        # self._process_features(limit)
        self._process_phenotype(limit)
        self._process_phenotype_cvterm(limit)

        # These must be processed in a specific order
        self._process_pub_dbxref(limit)
        # self._process_phendesc(limit)
        # self._process_feature_genotype(limit)
        # self._process_feature_pub(limit)
        # self._process_stock_genotype(limit)
        self._process_phenstatement(limit)   # these are G2P associations

        logger.info("Finished parsing.")

        self.load_bindings()
        for g in [self.graph, self.testgraph]:
            Assoc(self.name).load_all_properties(g)
            gu = GraphUtils(curie_map.get())
            gu.loadAllProperties(g)

        logger.info("Loaded %d nodes", len(self.graph))
        return

    def _process_genotypes(self, limit):
        """
        Add the genotype internal id to flybase mapping to the idhashmap.  Also, add them as individuals to the graph.

        Triples created:
        <genotype id> a GENO:intrinsic_genotype
        <genotype id> rdfs:label "<gvc> [bkgd]"

        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        line_counter = 0
        geno_hash = {}
        raw = '/'.join((self.rawdir, 'genotype'))
        logger.info("building labels for genotypes")
        gu = GraphUtils(curie_map.get())
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            for line in filereader:
                line_counter += 1

                (genotype_num, uniquename, description, name) = line

                # if self.testMode is True:
                #     if int(object_key) not in self.test_keys.get('genotype'):
                #         continue

                # add the internal genotype to pub mapping
                genotype_id = self._makeInternalIdentifier('genotype', genotype_num)
                if self.nobnodes:
                    genotype_id = ':'+genotype_id
                self.idhash['genotype'][genotype_num] = genotype_id

                if description == '':
                    description = None

                if not self.testMode and limit is not None and line_counter > limit:
                    pass
                else:
                    gu.addIndividualToGraph(g, genotype_id, uniquename, Genotype.genoparts['intrinsic_genotype'],
                                            description)
                    if name.strip() != '':
                        gu.addSynonym(g, genotype_id, name)

        return

    def _process_stocks(self, limit):
        """
        Add the genotype internal id to flybase mapping to the idhashmap.  Also, add them as individuals to the graph.

        Triples created:
        <genotype id> a GENO:intrinsic_genotype
        <genotype id> rdfs:label "<gvc> [bkgd]"

        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        line_counter = 0
        geno_hash = {}
        raw = '/'.join((self.rawdir, 'stock'))
        logger.info("building labels for stocks")
        gu = GraphUtils(curie_map.get())
        taxon = 'NCBITaxon:7227'
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            for line in filereader:
                line_counter += 1

                (stock_id, dbxref_id, organism_id, name, uniquename, description,
                 type_id, is_obsolete) = line
# 2       12153979        1       2       FBst0000002     w[*]; betaTub60D[2] Kr[If-1]/CyO        10670
                # if self.testMode is True:
                #     if int(object_key) not in self.test_keys.get('genotype'):
                #         continue

                stock_num = stock_id
                stock_id = 'FlyBase:'+uniquename
                self.idhash['stock'][stock_num] = stock_id
                stock_label = description

                # todo look up the species by organism_id in the hashmap
                organism_key = organism_id
                # taxon = self.idhash['organsim'][organism_key]

                # todo do something with the dbxref_id (external ids?)

                if not self.testMode and limit is not None and line_counter > limit:
                    pass
                else:
                    if is_obsolete == 't':
                        gu.addDeprecatedIndividual(g, stock_id)
                    else:
                        gu.addIndividualToGraph(g, stock_id, stock_label, taxon)

        return

    def _process_pubs(self, limit):
        """
        Add the genotype internal id to flybase mapping to the idhashmap.  Also, add them as individuals to the graph.

        Triples created:
        <genotype id> a GENO:intrinsic_genotype
        <genotype id> rdfs:label "<gvc> [bkgd]"

        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        line_counter = 0
        geno_hash = {}
        raw = '/'.join((self.rawdir, 'pub'))
        logger.info("building labels for pubs")
        gu = GraphUtils(curie_map.get())
        taxon = 'NCBITaxon:7227'
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            for line in filereader:
                (pub_id, title, volumetitle, volume, series_name, issue, pyear, pages, miniref,
                 type_id, is_obsolete, publisher, pubplace, uniquename) = line
# 2       12153979        1       2       FBst0000002     w[*]; betaTub60D[2] Kr[If-1]/CyO        10670
                # if self.testMode is True:
                #     if int(object_key) not in self.test_keys.get('genotype'):
                #         continue

                pub_num = pub_id
                pub_id = 'FlyBase:'+uniquename.strip()
                self.idhash['publication'][pub_num] = pub_id

                # TODO figure out the type of pub by type_id
                if not re.match('(FBrf|multi)', uniquename):
                    continue
                line_counter += 1

                r = Reference(pub_id)
                if title != '':
                    r.setTitle(title)
                if pyear != '':
                    r.setYear(str(pyear))
                if miniref != '':
                    r.setShortCitation(miniref)

                if not self.testMode and limit is not None and line_counter > limit:
                    pass
                else:
                    if is_obsolete == 't':
                        gu.addDeprecatedIndividual(g, pub_id)
                    else:
                        r.addRefToGraph(g)

        return

    def _process_environments(self, limit):
        """
        There's only a few (~30) environments in which the phenotypes are recorded...
        There are no externally accessible identifiers for environments, so we make anonymous nodes for now.
        Some of the environments are comprised of >1 of the other environments; we do some simple parsing to
        match the strings of the environmental labels to the other atomic components.

        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'environment'))
        logger.info("building labels for environment")
        env_parts = {}
        label_map = {}
        env = Environment(g)
        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (environment_id, uniquename, description) = line
                #22      heat sensitive | tetracycline conditional

                environment_num = environment_id
                environment_id = self._makeInternalIdentifier('environment',environment_num)
                if self.nobnodes:
                    environment_id = ':'+environment_id

                self.idhash['environment'][environment_num] = environment_id

                environment_label = uniquename
                env.addEnvironment(environment_id, environment_label)
                self.label_hash[environment_id] = environment_label

                # split up the environment into parts
                # if there's parts, then add them to the hash; we'll match the components in a second pass
                components = re.split('\|', uniquename)
                if len(components) > 1:
                    env_parts[environment_id] = components
                else:
                    label_map[environment_label] = environment_id

            #### end loop through file

        # build the environmental components
        for eid in env_parts:
            eid = eid.strip()
            for e in env_parts[eid]:
                # search for the environmental component by label
                env_id = label_map.get(e.strip())
                env.addComponentToEnvironment(eid, env_id)

        return

    def _process_features(self, limit):

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'feature'))
        logger.info("building labels for features")
        geno = Genotype(g)
        line_counter = 0
        gu = GraphUtils(curie_map.get())
        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (feature_id, dbxref_id, organism_id, name, uniquename, residues, seqlen, md5checksum, type_id,
                 is_analysis, timeaccessioned, timelastmodified, is_obsolete) = line

                line_counter += 1

# 30930111		340	Dwil\GK21498-RA	FBtr0252149		339	dae8eaaa6b6c2e3033f69039e970526f	368	f	2007-11-28 12:30:57.835613	2015-02-06 13:17:28.135903	t

                feature_num = feature_id
                feature_id = 'FlyBase:'+uniquename
                self.idhash['feature'][feature_num] = feature_id

                # now do something with it!
                # switch on type_id
                if name.strip() == '':
                    name = None

                if not self.testMode and limit is not None and line_counter > limit:
                    pass
                else:
                    if is_obsolete == 't':
                        gu.addDeprecatedIndividual(g, feature_id)
                    else:
                        gu.addIndividualToGraph(g, feature_id, name)

        return

    def _process_feature_genotype(self, limit):

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'feature_genotype'))
        logger.info("processing genotype features")
        geno = Genotype(g)
        line_counter = 0
        gu = GraphUtils(curie_map.get())
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            for line in filereader:
                line_counter += 1
                (feature_genotype_id, feature_id, genotype_id, chromosome_id, rank, cgroup, cvterm_id) = line
                # 1	23273518	2	23159230	0	0	60468
                feature_key = feature_id
                feature_id = self.idhash['feature'][feature_key]
                genotype_key = genotype_id
                genotype_id = self.idhash['genotype'][genotype_key]

                # what is cvterm_id for in this context???
                # cgroup is the order of composition of things in the genotype label.
                # sometimes the same feature is listed twice; not sure if this is a mistake, or zygosity, or?

                geno.addParts(feature_id, genotype_id, geno.object_properties['has_alternate_part'])

                # TODO we will build up the genotypes here... lots to do

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return

    def _process_phendesc(self, limit):
        """
        The description of the resulting phenotypes with the genotype+environment

        :param limit:
        :return:
        """

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'phendesc'))
        logger.info("processing G2P")
        geno = Genotype(g)
        line_counter = 0
        gu = GraphUtils(curie_map.get())
        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (phendesc_id, genotype_id, environment_id, description, type_id, pub_id) = line
                # 1	2	1	Hemizygous males are wild type, homozygous males are sterile.	60466	209729

                line_counter += 1
                phendesc_key = phendesc_id
                phendesc_id = self._makeInternalIdentifier('phendesc', phendesc_key)

                # for now, just attach the description to the genotype
                genotype_key = genotype_id
                genotype_id = self.idhash['genotype'][genotype_key]
                pub_key = pub_id
                pub_id = self.idhash['publication'][pub_key]

                environment_key = environment_id
                environment_id = self.idhash['environment'][environment_key]

                # TODO type id ==> ECO???

                # just make associations with abnormal phenotype
                phenotype_id = 'FBcv:0001347'
                assoc = G2PAssoc(self.name, genotype_id, phenotype_id)
                assoc.add_source(pub_id)
                assoc.set_description(description)
                assoc.set_environment(environment_id)
                assoc.add_association_to_graph(g)
                assoc_id = assoc.get_association_id()
                gu.addComment(g, assoc_id, phendesc_id)

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return

    def _process_feature_pub(self, limit):
        """
        The description of the resulting phenotypes with the genotype+environment

        :param limit:
        :return:
        """

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'feature_pub'))
        logger.info("processing feature_pub")

        line_counter = 0
        gu = GraphUtils(curie_map.get())

        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (feature_pub_id, feature_id, pub_id) = line
                # 1440    3175682 62137
                # 2       3160606 99159
                feature_key = feature_id
                feature_id = self.idhash['feature'][feature_key]
                pub_key = pub_id
                pub_id = self.idhash['publication'][pub_key]

                gu.addTriple(g, pub_id, gu.object_properties['mentions'], feature_id)

                line_counter += 1

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return


    def _process_stock_genotype(self, limit):
        """
        The description of the resulting phenotypes with the genotype+environment

        :param limit:
        :return:
        """

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'stock_genotype'))
        logger.info("processing stock genotype")
        geno = Genotype(g)
        line_counter = 0
        gu = GraphUtils(curie_map.get())

        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (stock_genotype_id, stock_id, genotype_id) = line

                stock_key = stock_id
                stock_id = self.idhash['stock'][stock_key]
                genotype_key = genotype_id
                genotype_id = self.idhash['genotype'][genotype_key]

                gu.addTriple(g, stock_id, geno.object_properties['has_genotype'], genotype_id)

                line_counter += 1

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return



    def _process_pub_dbxref(self, limit):
        """
        The description of the resulting phenotypes with the genotype+environment
        PRELIMINARY - MAY NOT BE NECESSARY TO IMPORT
        :param limit:
        :return:
        """

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'pub_dbxref'))
        logger.info("processing pub_dbxref")
        geno = Genotype(g)
        line_counter = 0
        gu = GraphUtils(curie_map.get())

        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (pub_dbxref_id, pub_id, dbxref_id, is_current) = line
                # 49648	43222	395730	t


                pub_key = pub_id
                pub_id = self.idhash['publication'][pub_key]

                # get any dbxrefs for pubs, including pmids and dois
                dbxref_key = dbxref_id
                if str(dbxref_key) in self.dbxrefs:
                    dbxrefs = self.dbxrefs[str(dbxref_key)]
                    # pub_dbs = [75, 51, 76, 95, 126]
                    pmid_ids = [50, 77, 275, 286, 347]
                    flybase_ids = [4]
                    isbn = [75, 51]
                    for d in dbxrefs:
                        dbxref_id = None
                        if int(d) in pmid_ids:
                            dbxref_id = 'PMID:'+dbxrefs[d].strip()
                        elif int(d) in isbn:
                            dbxref_id = 'ISBN:'+dbxrefs[d].strip()
                        elif int(d) == 161:
                            dbxref_id = 'DOI:'+dbxrefs[d].strip()
                        # elif int(d) == 4:
                        #     dbxref_id = 'FlyBase:'+dbxrefs[d].strip()

                        if dbxref_id is not None:
                            r = Reference(dbxref_id, Reference.ref_types['publication'])
                            r.addRefToGraph(g)
                            gu.addSameIndividual(g, pub_id, dbxref_id)
                            line_counter += 1

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return


    def _process_dbxref(self):
        """
        We bring in the dbxref identifiers and store them in a hashmap for lookup in other functions
        :param limit:
        :return:
        """

        raw = '/'.join((self.rawdir, 'dbxref'))
        logger.info("processing dbxrefs")
        line_counter = 0

        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (dbxref_id, db_id, accession, version, description, url) = line
                    # dbxref_id	db_id	accession	version	description	url
                    # 1	2	SO:0000000	""

                db_ids = {50: 'PMID',  # pubmed
                          68: 'RO',  # obo-rel
                          71: 'FBdv',  # FBdv
                          74: 'FBbt',  # FBbt
                          # 28:,  # genbank
                          30: 'OMIM',  # MIM
                          # 38,  # ncbi
                          75: 'ISBN',  # ISBN
                          46: 'PMID',  # PUBMED
                          51: 'ISBN',  # isbn
                          52: 'SO',  # so
                          # 76,  # http
                          77: 'PMID',  # PMID
                          80: 'FBcv',  # FBcv
                          # 95,  # MEDLINE
                          98: 'REACT',  # Reactome
                          103: 'CHEBI', # Chebi
                          102: 'MESH', # MeSH
                          106: 'OMIM', # OMIM
                          105: 'KEGG-path', # KEGG pathway
                          107: 'DOI', # doi
                          108: 'CL', # CL
                          114: 'CHEBI', # CHEBI
                          115: 'KEGG', # KEGG
                          116: 'PubChem', # PubChem
                          # 120, # MA???
                          3: 'GO',   # GO
                          4: 'FlyBase',   # FlyBase
                          # 126, # URL
                          128: 'PATO', # PATO
                          # 131, # IMG
                          2: 'SO',   # SO
                          136: 'MESH', # MESH
                          139: 'CARO', # CARO
                          140: 'NCBITaxon', # NCBITaxon
                          # 151, # MP  ???
                          161: 'DOI', # doi
                          36: 'BDGP',  # BDGP
                          # 55,  # DGRC
                          # 54,  # DRSC
                          # 169, # Transgenic RNAi project???
                          231: 'RO', # RO ???
                          180: 'NCBIGene', # entrezgene
                          # 192, # Bloomington stock center
                          197: 'UBERON', # Uberon
                          212: 'ENSEMBL', # Ensembl
                          # 129, # GenomeRNAi
                          275: 'PMID', # PubMed
                          286: 'PMID', # pmid
                          265: 'OMIM', # OMIM_Gene
                          266: 'OMIM', # OMIM_Phenotype
                          300: 'DOID', # DOID
                          302: 'MESH', # MSH
                          347: 'PMID', # Pubmed
                }  # the databases to fetch

                if accession.strip() != '' and int(db_id) in db_ids:
                    self.dbxrefs[dbxref_id] = {db_id:':'.join((db_ids.get(int(db_id)), accession.strip()))}
                elif url != '':
                    self.dbxrefs[dbxref_id] = {db_id:url.strip()}
                else:
                    continue

                line_counter += 1

        return

    def _process_phenotype(self, limit):
        """
        UNFINISHED - STUB ONLY
        :param limit:
        :return:
        """

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'phenotype'))
        logger.info("processing phenotype")
        geno = Genotype(g)
        line_counter = 0
        gu = GraphUtils(curie_map.get())

        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (phenotype_id, uniquename, observable_id, attr_id, value, cvalue_id, assay_id) = line

                # 8505	unspecified
                # 20142	mesothoracic leg disc | somatic clone	87719	60468		60468	60468
                # 8507	sex comb | ectopic	88877	60468		60468	60468
                # 8508	tarsal segment	83664	60468		60468	60468

                # for now make these as phenotypic classes - will need to xref at some point
                phenotype_key = phenotype_id
                phenotype_id = None
                phenotype_internal_id = self._makeInternalIdentifier('phenotype', phenotype_key)
                self.label_hash[phenotype_internal_id] = uniquename

                # here, we convert the phenotype into a uberpheno-style identifier, simply based on
                # the anatomical part that's affected...that is listed as the observable_id,
                # concatenated with the literal "PHENOTYPE"
                if observable_id in self.idhash['cvterm']:
                    phenotype_id = self.idhash['cvterm'][observable_id] + 'PHENOTYPE'

                phenotype_label = None
                if observable_id != '' and observable_id in self.idhash['cvterm']:
                    cvterm_id = self.idhash['cvterm'][observable_id]
                    if cvterm_id in self.label_hash:
                        phenotype_label = self.label_hash[cvterm_id]
                        phenotype_label += ' phenotype'
                    else:
                        logger.info('cvtermid=%s not in label_hash', cvterm_id)
                else:
                    logger.info("No observable id or label for %s: %s", phenotype_key, uniquename)

                # TODO store this composite phenotype in some way as a proper class definition?
                self.idhash['phenotype'][phenotype_key] = phenotype_id

                # TODO store the phenotype-to-assay for use in the

                if not self.testMode and limit is not None and line_counter > limit:
                    pass
                else:
                    if phenotype_id is not None:
                        gu.addClassToGraph(g, phenotype_id, phenotype_label)
                        line_counter += 1

        return

    def _process_phenstatement(self, limit):
        """
        UNFINISHED - STUB ONLY
        :param limit:
        :return:
        """

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        raw = '/'.join((self.rawdir, 'phenstatement'))
        logger.info("processing phenstatement")
        geno = Genotype(g)
        line_counter = 0
        gu = GraphUtils(curie_map.get())

        with open(raw, 'r') as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            f.readline()  # read the header row; skip
            for line in filereader:
                (phenstatement_id, genotype_id, environment_id, phenotype_id, type_id, pub_id) = line

                # 168549	166695	1	8507	60468	151256
                # 168550	166695	1	8508	60468	151256
                # 168551	166696	1	8509	60468	151256
                # 168552	166696	1	8510	60468	151256
                line_counter += 1
                phenstatement_key = phenstatement_id
                phenstatement_id = self._makeInternalIdentifier('phenstatement', phenstatement_key)
                genotype_key = genotype_id
                genotype_id = self.idhash['genotype'][genotype_key]
                environment_key = environment_id
                environment_id = self.idhash['environment'][environment_key]
                phenotype_key = phenotype_id
                phenotype_internal_id = self._makeInternalIdentifier('phenotype', phenotype_key)  # TEMP
                phenotype_internal_label = self.label_hash[phenotype_internal_id]
                phenotype_id = self.idhash['phenotype'][phenotype_key]
                pub_key = pub_id
                pub_id = self.idhash['publication'][pub_key]

                assoc = G2PAssoc(self.name, genotype_id, phenotype_id)
                assoc.set_environment(environment_id)
                assoc.add_source(pub_id)
                assoc.add_association_to_graph(g)
                assoc_id = assoc.get_association_id()
                gu.addComment(g, assoc_id, phenstatement_id)
                gu.addDescription(g, assoc_id, phenotype_internal_label)

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return

    def _process_phenotype_cvterm(self, limit):
        """
        These are the qualifiers for the phenotype location itself
        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        line_counter = 0
        geno_hash = {}
        raw = '/'.join((self.rawdir, 'phenotype_cvterm'))
        logger.info("processing phenotype cvterm mappings")
        gu = GraphUtils(curie_map.get())
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            for line in filereader:
                line_counter += 1

                (phenotype_cvterm_id, phenotype_id, cvterm_id, rank) = line

                # 4532	8507	60793	0
                # 4533	8513	60830	0

                # add the internal genotype to pub mapping
                phenotype_key = phenotype_id
                cvterm_key = cvterm_id
                phenotype_id = self.idhash['phenotype'][phenotype_key]
                if cvterm_key in self.idhash['cvterm']:
                    cvterm_id = self.idhash['cvterm'][cvterm_key]

                    self.idhash['phenotype'][phenotype_key] = cvterm_id
                    if phenotype_key not in self.phenocv:
                        self.phenocv[phenotype_id] = [cvterm_id]
                    else:
                        self.phenocv[phenotype_id] += [cvterm_id]
                else:
                    logger.info("Not storing the cvterm info for %s", cvterm_key)

        return


    def _process_cvterm(self):
        """
        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        line_counter = 0
        raw = '/'.join((self.rawdir, 'cvterm'))
        logger.info("processing cvterms")

        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')
            for line in filereader:
                line_counter += 1

                (cvterm_id, cv_id, definition, dbxref_id, is_obsolete, is_relationshiptype, name) = line

                # 316	6		1665919	0	0	rRNA_cleavage_snoRNA_primary_transcript
                # 28	5		1663309	0	0	synonym
                # 455	6		1665920	0	0	tmRNA

                cv_prefixes = {
                    6 : 'SO',
                    20: 'FBcv',
                    28: 'GO',
                    29: 'GO',
                    30: 'GO',
                    31: 'FBcv',
                    32: 'FBdv',
                    37: 'GO',   # these are relationships
                    73: 'DOID'
                }

                if int(cv_id) not in cv_prefixes:
                    continue
                cvterm_key = cvterm_id
                cvterm_id = self._makeInternalIdentifier('cvterm', cvterm_key)
                self.label_hash[cvterm_id] = name
                self.idhash['cvterm'][cvterm_key] = cvterm_id
                # look up the dbxref_id for the cvterm - hopefully it's one-to-one
                dbxrefs = self.dbxrefs.get(dbxref_id)
                if dbxrefs is not None:
                    if len(dbxrefs) > 1:
                        logger.info(">1 dbxref for this cvterm (%s: %s)", str(cvterm_id), name)
                    elif len(dbxrefs) == 1:
                        # replace the cvterm with the dbxref (external) identifier
                        did = dbxrefs.popitem()[1]
                        self.idhash['cvterm'][cvterm_key] = did  # get the value
                        # also add the label to the dbxref
                        self.label_hash[did] = name
        return

    # def _process_organism(self, limit):
    #     """
    #     The description of the resulting phenotypes with the genotype+environment
    #     PRELIMINARY - MAY NOT BE NECESSARY TO IMPORT
    #     :param limit:
    #     :return:
    #     """
    #
    #     if self.testMode:
    #         g = self.testgraph
    #     else:
    #         g = self.graph
    #
    #     raw = '/'.join((self.rawdir, 'stock_genotype'))
    #     logger.info("processing stock genotype")
    #     geno = Genotype(g)
    #     line_counter = 0
    #     gu = GraphUtils(curie_map.get())
    #
    #     with open(raw, 'r') as f:
    #         filereader = csv.reader(f, delimiter='\t', quotechar='\"')
    #         f.readline()  # read the header row; skip
    #         for line in filereader:
    #             (organism_id, abbreviation, genus, species, common_name, comment) = line
    #             # 1	Dmel	Drosophila	melanogaster	fruit fly
    #             # 2	Comp	Computational	result
    #
    #             line_counter += 1
    #
    #             if not self.testMode and limit is not None and line_counter > limit:
    #                 break
    #
    #     return

    def _makeInternalIdentifier(self, prefix, key):
        """
        This is a special Flybase-to-MONARCH-ism.  Flybase tables have unique keys that we use here, but don't want
        to necessarily re-distribute those internal identifiers.  Therefore, we make them into keys in a consistent
        way here.
        :param prefix: the object type to prefix the key with, since the numbers themselves are not unique across tables
        :param key: the number (unique key)
        :return:
        """
        iid = '_fb'+prefix+'key'+key
        if self.nobnodes:
            iid = ':'+ iid

        return iid


    # def getTestSuite(self):
    #     import unittest
    #     from tests.test_flybase import FlyBaseTestCase
    #
    #     test_suite = unittest.TestLoader().loadTestsFromTestCase(FlyBaseTestCase)
    #
    #     return test_suite
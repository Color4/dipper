import csv
import logging
import re
import gzip
from bs4 import BeautifulSoup
from dipper.sources.Source import Source
from dipper.models.Dataset import Dataset
from dipper.models.G2PAssoc import G2PAssoc
from dipper.models.Genotype import Genotype
from dipper.models.OrthologyAssoc import OrthologyAssoc
from dipper.utils.GraphUtils import GraphUtils
from dipper import curie_map

logger = logging.getLogger(__name__)


class AnimalQTLdb(Source):

    files = {
        'cattle_btau_bp': {'file': 'QTL_Btau_4.6.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_Btau_4.6.gff.txt.gz'},
        'cattle_umd_bp': {'file': 'QTL_UMD_3.1.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_UMD_3.1.gff.txt.gz'},
        'cattle_cm': {'file': 'cattle_QTLdata.txt',
                 'url': 'http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/cattle_QTLdata.txt'},
        'chicken_bp': {'file': 'QTL_GG_4.0.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_GG_4.0.gff.txt.gz'},
        'chicken_cm': {'file': 'chicken_QTLdata.txt',
                 'url': 'http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/chicken_QTLdata.txt'},
        'pig_bp': {'file': 'QTL_SS_10.2.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_SS_10.2.gff.txt.gz'},
        'pig_cm': {'file': 'pig_QTLdata.txt',
                 'url': 'http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/pig_QTLdata.txt'},
        'sheep_bp': {'file': 'QTL_OAR_3.1.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_OAR_3.1.gff.txt.gz'},
        'sheep_cm': {'file': 'sheep_QTLdata.txt',
                 'url': 'http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/sheep_QTLdata.txt'},
        'horse_bp': {'file': 'QTL_EquCab2.0.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_EquCab2.0.gff.txt.gz'},
        'horse_cm': {'file': 'horse_QTLdata.txt',
                 'url': 'http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/horse_QTLdata.txt'},
        'rainbow_trout_cm': {'file': 'rainbow_trout_QTLdata.txt',
                 'url': 'http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/rainbow_trout_QTLdata.txt'},
        'trait_mappings': {'file': 'trait_mappings',
                 'url': 'http://www.animalgenome.org/QTLdb/export/trait_mappings.csv'}
    }

    # I do not love putting these here; but I don't know where else to put them
    test_ids = {
    }

    def __init__(self):
        Source.__init__(self, 'animalqtldb')

        # update the dataset object with details about this resource
        # TODO put this into a conf file?
        self.dataset = Dataset('animalqtldb', 'Animal QTL db', 'http://www.animalgenome.org/cgi-bin/QTLdb/index', None, None)

        # source-specific warnings.  will be cleared when resolved.

        return

    def fetch(self, is_dl_forced):
        self.get_files(is_dl_forced)
        #if self.compare_checksums():
            #logger.debug('Files have same checksum as reference')
        #else:
            #raise Exception('Reference checksums do not match disk')
        return

    def parse(self, limit=None):
        """

        :param limit:
        :return:
        """
        if limit is not None:
            logger.info("Only parsing first %s rows fo each file", str(limit))

        logger.info("Parsing files...")

        if self.testOnly:
            self.testMode = True

        self._process_trait_mappings(('/').join((self.rawdir, self.files['trait_mappings']['file'])), limit)
        #self._alternate_process_QTLs_genomic_location(('/').join((self.rawdir, self.files['chicken_bp']['file'])), 'AQTLChicken:', 'AQTLTraitChicken:', 'NCBITaxon:9031', limit)
        #self._process_QTLs_genomic_location(('/').join((self.rawdir, self.files['chicken_bp']['file'])), 'AQTLChicken:', 'AQTLTraitChicken:', 'NCBITaxon:9031', limit)

        #logger.info("Processing QTLs with genetic locations")
        #self._process_QTLs_genetic_location(('/').join((self.rawdir, self.files['cattle_cm']['file'])), 'AQTLCattle:', 'AQTLTraitCattle:', 'NCBITaxon:9913', limit)
        #self._process_QTLs_genetic_location(('/').join((self.rawdir, self.files['chicken_cm']['file'])), 'AQTLChicken:', 'AQTLTraitChicken:', 'NCBITaxon:9031', limit)
        #self._process_QTLs_genetic_location(('/').join((self.rawdir, self.files['pig_cm']['file'])), 'AQTLPig:', 'AQTLTraitPig:', 'NCBITaxon:9823', limit)
        #self._process_QTLs_genetic_location(('/').join((self.rawdir, self.files['sheep_cm']['file'])), 'AQTLSheep:', 'AQTLTraitSheep:', 'NCBITaxon:9940', limit)
        #self._process_QTLs_genetic_location(('/').join((self.rawdir, self.files['horse_cm']['file'])), 'AQTLHorse:', 'AQTLTraitHorse:', 'NCBITaxon:9796', limit)
        #self._process_QTLs_genetic_location(('/').join((self.rawdir, self.files['rainbow_trout_cm']['file'])), 'AQTLRainbowTrout:', 'AQTLTraitRainbowTrout:', 'NCBITaxon:8022', limit)

        # TODO: Need to bring in the Animal QTL trait map?
        logger.info("Finished parsing")

        self.load_bindings()

        logger.info("Found %d nodes", len(self.graph))
        return


    #TODO: Abstract this into a general function
    # Need to pass in: file, qtl prefix, trait prefix, taxon,

    def _process_QTLs_genetic_location(self, raw, qtl_prefix, trait_prefix, taxon_id, limit=None):
        """
        This method processes

        Triples created:

        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph
        line_counter = 0
        geno = Genotype(g)
        gu = GraphUtils(curie_map.get())
        #raw = ('/').join((self.rawdir, self.files['cattle_cm']['file']))
        with open(raw, 'r', encoding="iso-8859-1") as csvfile:
            filereader = csv.reader(csvfile, delimiter='\t', quotechar='\"')
            for row in filereader:
                line_counter += 1
                (qtl_id, qtl_symbol, trait_name, assotype, empty, chromosome, position_cm, range_cm,
                 flankmark_a2, flankmark_a1, peak_mark, flankmark_b1, flankmark_b2, exp_id, model, test_base,
                 sig_level, lod_score, ls_mean, p_values, f_statistics, variance, bayes_value, likelihood_ratio,
                 trait_id, dom_effect, add_effect, pubmed_id, gene_id, gene_id_src, gene_id_type, empty2) = row

                #if self.testMode and disease_id not in self.test_ids['disease']:
                    #continue
                #print(row)

                #FIXME: Not sure that I like these prefixes. Is there a better approach?
                qtl_id = qtl_prefix+qtl_id
                trait_id = trait_prefix+trait_id

                #FIXME: For assotype, the QTL is indicated either as a QTL or an Association.
                # Should Associations be handled differently?

                # Add QTL to graph
                gu.addIndividualToGraph(g, qtl_id, qtl_symbol, geno.genoparts['QTL'])

                geno.addTaxon(taxon_id,qtl_id)
                # Add trait to graph as a phenotype - QTL has phenotype?


                if re.match('ISU.*', pubmed_id):
                    pub_id = 'AQTLPub:'+pubmed_id.strip()
                else:
                    pub_id = 'PMID:'+pubmed_id.strip()

                # Add publication
                gu.addIndividualToGraph(g,pub_id,None)
                eco_id = "ECO:0000059"  # Using experimental phenotypic evidence
                assoc_id = self.make_id((qtl_id+trait_id+pub_id))
                assoc = G2PAssoc(assoc_id, qtl_id, trait_id, pub_id, eco_id)
                assoc.addAssociationNodeToGraph(g)

                # Add gene to graph,
                #TODO: Should this be altered this to an 'alternate locus' like in CTD, elsewhere.
                # As it isn't the gene tha
                if gene_id_src == 'NCBIgene' and gene_id is not None and gene_id != '':
                    gene_id = 'NCBIGene:'+gene_id.strip()
                    # Note: no gene labels provided, NIF view used NCBIGene table lookups to get symbols.
                    geno.addGene(gene_id, None)

                # Add cm data as location?

                # Add publication

                if (not self.testMode) and (limit is not None and line_counter > limit):
                    break

        #logger.info("Done with QTLs")
        return

    def _process_QTLs_genomic_location(self, raw, qtl_prefix, trait_prefix, taxon_id, limit=None):
        """
        This method

        Triples created:

        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph
        line_counter = 0
        geno = Genotype(g)
        gu = GraphUtils(curie_map.get())

        with gzip.open(raw, 'rt') as tsvfile:
            reader = csv.reader(tsvfile, delimiter="\t")
            for row in reader:
                if re.match('^#', ' '.join(row)):
                    next
                else:
                    (chromosome, qtl_source, qtl_type, start_bp, stop_bp, frame, strand, score, multi) = row
                    #print(multi)
                    element_hash = {}
                    qtl_id = ''
                    trait_name = ''
                    trait_symbol = ''
                    pub_id = ''
                    trait_id = ''
                    peak_cm = ''
                    gene_id = ''
                    cmo_name = ''
                    pto_name = ''
                    vto_name = ''
                    significance = ''
                    p_value = ''
                    flankmarkers = ''
                    map_type = ''
                    model = ''
                    test_base = ''
                    gene_id_src = ''
                    breed = ''

                    #How best to split up the multi column?
                    # Could do it in a hash...
                    multi_list = multi.split(';')
                    #print(multi_list)
                    for i in multi_list:
                        elements = str(i)
                        #print(elements)
                        if re.match('.*=.*', elements):

                            # Variables available in 'multi' column: QTL_ID,Name,Abbrev,PUBMED_ID,trait_ID,trait,
                            # FlankMarkers,VTO_name,Map_Type,Significance,P-value,Model,Test_Base,Variance,
                            # Bayes-value,PTO_name,gene_IDsrc,peak_cM,CMO_name,gene_ID,F-Stat,LOD-score,Additive_Effect,
                            # Dominance_Effect,Likelihood_Ratio,LS-means,Breed

                            # Unused variables available in 'multi' column: trait (duplicate with Name),Variance,Bayes-value,
                            # F-Stat,LOD-score,Additive_Effect,Dominance_Effect,Likelihood_Ratio,LS-means

                            element_pair = elements.split('=')
                            key = element_pair[0]
                            value = element_pair[1]
                            if value != '-' and value != '' and value is not None:
                                if key == 'QTL_ID':
                                    qtl_id = value
                                elif key == 'Name':
                                    trait_name = value
                                elif key == 'Abbrev':
                                    trait_symbol = value
                                elif key == 'PUBMED_ID':
                                    pub_id = value
                                    if re.match('ISU.*', pub_id):
                                        pub_id = 'AQTLPub:'+pub_id.strip()
                                    else:
                                        pub_id = 'PMID:'+pub_id.strip()
                                elif key == 'trait_ID':
                                    trait_id = value
                                elif key == 'peak_cM':
                                    peak_cm = value
                                elif key == 'gene_ID':
                                    gene_id = value
                                elif key == 'VTO_name':
                                    vto_name = value
                                elif key == 'CMO_name':
                                    cmo_name = value
                                elif key == 'PTO_name':
                                    pto_name = value
                                elif key == 'Significance':
                                    significance = value
                                elif key == 'P-value':
                                    p_value = value
                                elif key == 'FlankMarkers':
                                    flankmarkers = value
                                elif key == 'Map_Type':
                                    map_type = value
                                elif key == 'Model':
                                    model = value
                                elif key == 'Test_Base':
                                    test_base = value
                                elif key == 'gene_IDsrc':
                                    gene_id_src = value
                                elif key == 'Breed':
                                    breed = value

                    qtl_id = qtl_prefix+qtl_id
                    trait_id = trait_prefix+trait_id
                    #FIXME: For assotype, the QTL is indicated either as a QTL or an Association.
                    # Should Associations be handled differently?

                    # Add QTL to graph
                    gu.addIndividualToGraph(g, qtl_id, None, geno.genoparts['QTL'])

                    geno.addTaxon(taxon_id,qtl_id)
                    # Add trait to graph as a phenotype - QTL has phenotype?
                    # Add publication
                    gu.addIndividualToGraph(g,pub_id,None)
                    eco_id = "ECO:0000059"  # Using experimental phenotypic evidence
                    assoc_id = self.make_id((qtl_id+trait_id+pub_id))
                    assoc = G2PAssoc(assoc_id, qtl_id, trait_id, pub_id, eco_id)
                    assoc.addAssociationNodeToGraph(g)

        logger.info("Done with QTLs")
        return


    def _process_trait_mappings(self, raw, limit=None):
        """
        This method

        Triples created:

        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph
        line_counter = 0
        geno = Genotype(g)
        gu = GraphUtils(curie_map.get())

        with open(raw, 'r') as csvfile:
            filereader = csv.reader(csvfile, delimiter=',')
            row_count = sum(1 for row in filereader)
            row_count = row_count - 1



        with open(raw, 'r') as csvfile:
            filereader = csv.reader(csvfile, delimiter=',')
            next(filereader, None)
            for row in filereader:
                line_counter += 1
                if line_counter < row_count:
                    (vto_id, pto_id, cmo_id, ato_id, species, trait_class, trait_type, qtl_count) = row

                    if re.match('VT:.*', vto_id):
                        print(vto_id)

                    if re.match('PT:.*', pto_id):
                        print(pto_id)
                    if re.match('CMO:.*', cmo_id):
                        print(cmo_id)
                    #print(ato_id)
                    print(row)








        logger.info("Done with trait mappings")
        return

import csv
import re
import logging
import gzip
import io
from dipper.sources.ZFIN import ZFIN
from dipper.sources.WormBase import WormBase

from dipper.sources.Source import Source
from dipper.models.assoc.Association import Assoc
from dipper.models.assoc.G2PAssoc import G2PAssoc
from dipper.models.Genotype import Genotype
from dipper.models.Reference import Reference
from dipper.models.Model import Model
from dipper import config


logger = logging.getLogger(__name__)
GOGA = 'http://geneontology.org/gene-associations'
FTPEBI = 'ftp://ftp.uniprot.org/pub/databases/'
UPCR = 'uniprot/current_release/knowledgebase/'


class GeneOntology(Source):
    """
    This is the parser for the
    [Gene Ontology Annotations](http://www.geneontology.org),
    from which we process gene-process/function/subcellular
    location associations.

    We generate the GO graph to include the following information:
    * genes
    * gene-process
    * gene-function
    * gene-location

    We process only a subset of the organisms:

    Status: IN PROGRESS / INCOMPLETE

    """

    files = {
        '9615': {
            'file': 'gene_association.goa_dog.gz',
            'url': GOGA + '/goa_dog.gaf.gz'},
        '7227': {
            'file': 'gene_association.fb.gz',
            'url': GOGA + '/gene_association.fb.gz'},
        '7955': {
            'file': 'gene_association.zfin.gz',
            'url': GOGA + '/gene_association.zfin.gz'},
        '10090': {
            'file': 'gene_association.mgi.gz',
            'url': GOGA + '/gene_association.mgi.gz'},
        '10116': {
            'file': 'gene_association.rgd.gz',
            'url': GOGA + '/gene_association.rgd.gz'},
        '6239': {
            'file': 'gene_association.wb.gz',
            'url': GOGA + '/gene_association.wb.gz'},
        '9823': {
            'file': 'gene_association.goa_ref_pig.gz',
            'url': GOGA + '/goa_pig.gaf.gz'},
        '9031': {
            'file': 'gene_association.goa_ref_chicken.gz',
            'url': GOGA + '/goa_chicken.gaf.gz'},
        '9606': {
            'file': 'gene_association.goa_ref_human.gz',
            'url': GOGA + '/goa_human.gaf.gz'},
        '9913': {
            'file': 'goa_cow.gaf.gz',
            'url': GOGA + '/goa_cow.gaf.gz'},
        '559292': {
            'file': 'gene_association.sgd.gz',
            'url': GOGA + '/gene_association.sgd.gz'},
        '4896': {
            'file': 'gene_association.pombase.gz',
            'url': GOGA + '/gene_association.pombase.gz'},
        # consider this after most others - should this be part of GO?
        # 'multispecies': {
        #   'file': 'gene_association.goa_uniprot.gz',
        #   'url': FTPEBI + 'GO/goa/UNIPROT/gene_association.goa_uniprot.gz'},
        'go-references': {
            'file': 'GO.references',
            'url': 'http://www.geneontology.org/doc/GO.references'},
        'id-map': {
            'file': 'idmapping_selected.tab.gz',
            'url':  FTPEBI + UPCR + 'idmapping/idmapping_selected.tab.gz'
        }
    }

    map_files = {
        'eco_map': 'http://purl.obolibrary.org/obo/eco/gaf-eco-mapping.txt',
    }

    def __init__(self, graph_type, are_bnodes_skolemized, tax_ids=None):
        super().__init__(
            graph_type,
            are_bnodes_skolemized,
            'go',
            ingest_title='Gene Ontology',
            ingest_url='http://www.geneontology.org',
            license_url=None,
            data_rights='http://geneontology.org/page/use-and-license'
            # file_handle=None
        )

        # Defaults
        self.tax_ids = tax_ids
        self.test_ids = list()
        if self.tax_ids is None:
            self.tax_ids = [9606, 10090, 7955]
            logger.info("No taxa set.  Defaulting to %s", str(tax_ids))
        else:
            logger.info("Filtering on the following taxa: %s", str(tax_ids))

        if 'test_ids' not in config.get_config() or 'gene' \
                not in config.get_config()['test_ids']:
            logger.warning("not configured with gene test ids.")
        else:
            self.test_ids = config.get_config()['test_ids']['gene']

        return

    def fetch(self, is_dl_forced=False):

        self.get_files(is_dl_forced)
        return

    def parse(self, limit=None):
        if limit is not None:
            logger.info("Only parsing first %s rows of each file", limit)
        logger.info("Parsing files...")

        if self.testOnly:
            self.testMode = True

        eco_map = self.get_eco_map(self.map_files['eco_map'])

        # build the id map for mapping uniprot ids to genes
        uniprot_entrez_id_map = self.get_uniprot_entrez_id_map()

        for txid_num in self.files:

            if txid_num in ['go-references', 'id-map']:
                continue

            if not self.testMode and int(txid_num) not in self.tax_ids:
                continue

            gaffile = '/'.join((self.rawdir, self.files.get(txid_num)['file']))
            self.process_gaf(gaffile, limit, uniprot_entrez_id_map, eco_map)

        logger.info("Finished parsing.")

        return

    def process_gaf(self, file, limit, id_map=None, eco_map=None):

        if self.testMode:
            graph = self.testgraph
        else:
            graph = self.graph

        model = Model(graph)
        geno = Genotype(graph)
        logger.info("Processing Gene Associations from %s", file)
        line_counter = 0

        if 7955 in self.tax_ids:
            zfin = ZFIN(self.graph_type, self.are_bnodes_skized)
        if 6239 in self.tax_ids:
            wbase = WormBase(self.graph_type, self.are_bnodes_skized)

        with gzip.open(file, 'rb') as csvfile:
            filereader = csv.reader(
                io.TextIOWrapper(csvfile, newline=""), delimiter='\t', quotechar='\"')
            for row in filereader:
                line_counter += 1
                # comments start with exclamation
                if re.match(r'!', ''.join(row)):
                    continue

                if len(row) > 17 or len(row) < 15:
                    logger.warning(
                        "Wrong number of columns {}, expected 15 or 17\n{}"
                        .format(len(row), row)
                    )
                    continue

                if 17 > len(row) >= 15:
                    row += [""] * (17 - len(row))

                (db,
                 gene_num,
                 gene_symbol,
                 qualifier,
                 go_id,
                 ref,
                 eco_symbol,
                 with_or_from,
                 aspect,
                 gene_name,
                 gene_synonym,
                 object_type,
                 taxon,
                 date,
                 assigned_by,
                 annotation_extension,
                 gene_product_form_id) = row

                # test for required fields
                if (db == '' or gene_num == '' or gene_symbol == '' or
                        go_id == '' or ref == '' or eco_symbol == '' or
                        aspect == '' or object_type == '' or taxon == '' or
                        date == '' or assigned_by == ''):
                    logger.error(
                        "Missing required part of annotation on row %d:\n"+'\t'
                        .join(row), line_counter)
                    continue

                # deal with qualifier NOT, contributes_to, colocalizes_with
                if re.search(r'NOT', qualifier):
                    continue

                db = self.resolve(db, False)  # return 'db' if no mapping needed
                uniprotid = None
                gene_id = None
                if db == 'UniProtKB':
                    mapped_ids = id_map.get(gene_num)
                    if id_map is not None and mapped_ids is not None:
                        if len(mapped_ids) == 1:
                            gene_id = mapped_ids[0]
                            uniprotid = ':'.join((db, gene_num))
                            gene_num = re.sub(r'\w+\:', '', gene_id)
                        elif len(mapped_ids) > 1:
                            # logger.warning(
                            #   "Skipping gene id mapped for >1 gene %s -> %s",
                            #    gene_num, str(mapped_ids))
                            continue
                    else:
                        continue
                elif db == 'MGI':
                    gene_num = re.sub(r'MGI:', '', gene_num)
                    gene_id = ':'.join((db, gene_num))
                    gene_id = re.sub(r'MGI\:MGI\:', 'MGI:', gene_id)
                else:
                    gene_id = ':'.join((db, gene_num))

                if self.testMode and not(
                        re.match(r'NCBIGene', gene_id) and
                        int(gene_num) in self.test_ids):
                    continue

                model.addClassToGraph(gene_id, gene_symbol)
                if gene_name != '':
                    model.addDescription(gene_id, gene_name)
                if gene_synonym != '':
                    for s in re.split(r'\|', gene_synonym):
                        model.addSynonym(gene_id, s.strip())
                if re.search(r'\|', taxon):
                    # TODO add annotations with >1 taxon
                    logger.info(
                        ">1 taxon (%s) on line %d.  skipping", taxon, line_counter)
                else:
                    tax_id = re.sub(r'taxon:', 'NCBITaxon:', taxon)
                    geno.addTaxon(tax_id, gene_id)

                assoc = Assoc(graph, self.name)

                assoc.set_subject(gene_id)
                assoc.set_object(go_id)

                try:
                    eco_id = eco_map[eco_symbol]
                    assoc.add_evidence(eco_id)
                except KeyError:
                    logger.error("Evidence code (%s) not mapped", eco_symbol)

                refs = re.split(r'\|', ref)
                for r in refs:
                    r = r.strip()
                    if r != '':
                        prefix = self.resolve(r.split(':')[0], False)
                        r = re.sub(r'MGI\:MGI\:', 'MGI:', r)
                        ref = Reference(graph, r)
                        if re.match(r'PMID', r):
                            ref_type = self.globaltt['journal article']
                            ref.setType(ref_type)
                        ref.addRefToGraph()
                        assoc.add_source(r)

                # TODO add the source of the annotations from assigned by?

                rel = self.resolve(aspect, mandatory=False)
                if aspect == rel:
                    if aspect == 'F' and re.search(r'contributes_to', qualifier):
                        assoc.set_relationship(self.globaltt['contributes to'])
                    else:
                        logger.error(
                            "Aspect: %s with qualifier: %s  is not recognized",
                            aspect, qualifier)
                else:
                    assoc.set_relationship(rel)
                if uniprotid is not None:
                    assoc.set_description('Mapped from ' + uniprotid)
                # object_type should be one of:
                # protein_complex; protein; transcript; ncRNA; rRNA; tRNA;
                # snRNA; snoRNA; any subtype of ncRNA in the Sequence Ontology.
                # If the precise product type is unknown,
                # gene_product should be used

                assoc.add_association_to_graph()

                # Derive G2P Associations from IMP annotations
                # in version 2.1 Pipe will indicate 'OR'
                # and Comma will indicate 'AND'.
                # in version 2.0, multiple values are separated by pipes
                # where the pipe has been used to mean 'AND'
                if eco_symbol == 'IMP' and with_or_from != '':
                    withitems = re.split(r'\|', with_or_from)
                    phenotypeid = go_id+'PHENOTYPE'
                    # create phenotype associations
                    for i in withitems:
                        if i == '' or re.match(
                                r'(UniProtKB|WBPhenotype|InterPro|HGNC)', i):
                            logger.warning(
                                "Don't know what having a uniprot id " +
                                "in the 'with' column means of %s", uniprotid)
                            continue
                        i = re.sub(r'MGI\:MGI\:', 'MGI:', i)
                        i = re.sub(r'WB:', 'WormBase:', i)

                        # for worms and fish, they might give a RNAi or MORPH
                        # in these cases make a reagent-targeted gene
                        if re.search('MRPHLNO|CRISPR|TALEN', i):
                            targeted_gene_id = zfin.make_targeted_gene_id(gene_id, i)
                            geno.addReagentTargetedGene(i, gene_id, targeted_gene_id)
                            # TODO PYLINT why is this:
                            # Redefinition of assoc type from
                            # dipper.models.assoc.Association.Assoc to
                            # dipper.models.assoc.G2PAssoc.G2PAssoc
                            assoc = G2PAssoc(
                                graph, self.name, targeted_gene_id, phenotypeid)
                        elif re.search(r'WBRNAi', i):
                            targeted_gene_id = wbase.make_reagent_targeted_gene_id(
                                gene_id, i)
                            geno.addReagentTargetedGene(i, gene_id, targeted_gene_id)
                            assoc = G2PAssoc(
                                graph, self.name, targeted_gene_id, phenotypeid)
                        else:
                            assoc = G2PAssoc(graph, self.name, i, phenotypeid)
                        for r in refs:
                            r = r.strip()
                            if r != '':
                                prefix = re.split(r':', r)[0]
                                r = re.sub(
                                    prefix, self.localtt[prefix], r)
                                r = re.sub(r'MGI\:MGI\:', 'MGI:', r)
                                assoc.add_source(r)
                                # experimental phenotypic evidence
                                assoc.add_evidence(
                                    self.globaltt['experimental phenotypic evidence'])
                        assoc.add_association_to_graph()
                        # TODO should the G2PAssoc be
                        # the evidence for the GO assoc?

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return

    def get_uniprot_entrez_id_map(self):
        logger.info("Mapping Uniprot ids to Entrez/ENSEMBL gene ids")
        import sys
        id_map = {}
        file = '/'.join((self.rawdir, self.files['id-map']['file']))
        with gzip.open(file, 'rb') as csvfile:
            csv.field_size_limit(sys.maxsize)
            filereader = csv.reader(io.TextIOWrapper(csvfile, newline=""),
                                    delimiter='\t', quotechar='\"')
            for row in filereader:
                (uniprotkb_ac, uniprotkb_id, geneid, refseq, gi, pdb, go,
                 uniref100, unifref90, uniref50, uniparc, pir, ncbitaxon, mim,
                 unigene, pubmed, embl, embl_cds, ensembl, ensembl_trs,
                 ensembl_pro, other_pubmed) = row

                if int(ncbitaxon) not in self.tax_ids:
                    continue
                if geneid.strip() != '':
                    idlist = re.split(r';', geneid)
                    id_map[
                        uniprotkb_ac.strip()] = ['NCBIGene:'+i.strip() for i in idlist]
                elif ensembl.strip() != '':
                    idlist = re.split(r';', ensembl)
                    id_map[uniprotkb_ac.strip()] = [
                        'ENSEMBL:'+i.strip() for i in idlist]

        logger.info("Acquired %i uniprot-entrez mappings", len(id_map))

        return id_map

    def getTestSuite(self):
        import unittest
        from tests.test_geneontology import GeneOntologyTestCase

        test_suite = unittest.TestLoader().loadTestsFromTestCase(GeneOntologyTestCase)

        return test_suite

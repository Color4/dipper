import csv
import re
import logging
import gzip
import io

from dipper.sources.Source import Source
from dipper.models.assoc.Association import Assoc
from dipper.models.Genotype import Genotype
from dipper.models.Reference import Reference
from dipper.models.Dataset import Dataset
from dipper.utils.GraphUtils import GraphUtils
from dipper import curie_map
from dipper import config


logger = logging.getLogger(__name__)


class GeneOntology(Source):
    """
    This is the parser for the [Gene Ontology Annotations](http://www.geneontology.org),
    from which we process gene-process/function/subcellular location associations.

    We generate the GO graph to include the following information:
    * genes
    * gene-process
    * gene-function
    * gene-location

    We process only a subset of the organisms:

    Status: IN PROGRESS / INCOMPLETE

    """

    files = {
        '9615': {'file': 'gene_association.goa_dog.gz',
                 'url': 'http://geneontology.org/gene-associations/gene_association.goa_dog.gz'},
        '7227': {'file': 'gene_association.fb.gz',
                 'url': 'http://geneontology.org/gene-associations/gene_association.fb.gz'},
        '7955': {'file': 'gene_association.zfin.gz',
                 'url': 'http://geneontology.org/gene-associations/gene_association.zfin.gz'},
        '10090': {'file': 'gene_association.mgi.gz',
                  'url': 'http://geneontology.org/gene-associations/gene_association.mgi.gz'},
        '10116': {'file': 'gene_association.rgd.gz',
                  'url': 'http://geneontology.org/gene-associations/gene_association.rgd.gz'},
        '6239': {'file': 'gene_association.wb.gz',
                 'url': 'http://geneontology.org/gene-associations/gene_association.wb.gz'},
        '9823': {'file': 'gene_association.goa_ref_pig.gz',
                 'url': 'http://geneontology.org/gene-associations/gene_association.goa_ref_pig.gz'},
        '9031': {'file': 'gene_association.goa_ref_chicken.gz',
                 'url': 'http://geneontology.org/gene-associations/gene_association.goa_ref_chicken.gz'},
        '9606': {'file': 'gene_association.goa_ref_human.gz',
                 'url': 'http://geneontology.org/gene-associations/gene_association.goa_ref_human.gz'},
        '9913': {'file': 'gene_association.goa_ref_cow.gz',
                 'url': 'http://geneontology.org/gene-associations/gene_association.goa_ref_cow.gz'},
        # consider this after most others - should this be part of GO?
        # 'multispecies': {'file': 'gene_association.goa_uniprot.gz',
        # 'url': 'ftp://ftp.ebi.ac.uk/pub/databases/GO/goa/UNIPROT/gene_association.goa_uniprot.gz'},
        'go-references': {'file': 'GO.references',
                          'url': 'http://www.geneontology.org/doc/GO.references'},
        'id-map': {
            'file': 'idmapping_selected.tab.gz',
            'url': 'ftp://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/idmapping/idmapping_selected.tab.gz'
        }
    }

    def __init__(self, tax_ids=None):
        Source.__init__(self, 'go')

        # Defaults
        self.tax_ids = tax_ids
        if self.tax_ids is None:
            self.tax_ids = [9606, 10090, 7955]
            logger.info("No taxa set.  Defaulting to %s", str(tax_ids))
        else:
            logger.info("Filtering on the following taxa: %s", str(tax_ids))

        # update the dataset object with details about this resource
        # NO LICENSE for this resource
        self.dataset = Dataset('go', 'GeneOntology', 'http://www.geneontology.org', None,
                               "https://creativecommons.org/licenses/by/4.0/legalcode",
                               'http://geneontology.org/page/use-and-license')

        if 'test_ids' not in config.get_config() or 'gene' not in config.get_config()['test_ids']:
            logger.warn("not configured with gene test ids.")
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

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        self.nobnodes = True  # FIXME

        # build the id map for mapping uniprot ids to genes
        uniprot_entrez_id_map = self.get_uniprot_entrez_id_map()

        for s in self.files:

            if s in ['go-references', 'id-map']:
                continue

            if not self.testMode and int(s) not in self.tax_ids:
                continue

            file = '/'.join((self.rawdir, self.files.get(s)['file']))
            self.process_gaf(file, limit, uniprot_entrez_id_map)

        logger.info("Finished parsing.")

        self.load_bindings()
        gu = GraphUtils(curie_map.get())
        gu.loadAllProperties(g)
        gu.loadObjectProperties(g, Genotype.object_properties)

        logger.info("Found %d nodes in graph", len(self.graph))
        logger.info("Found %d nodes in testgraph", len(self.testgraph))

        return

    def process_gaf(self, file, limit, id_map=None):

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        gu = GraphUtils(curie_map.get())
        geno = Genotype(g)
        logger.info("Processing Gene Associations from %s", file)
        line_counter = 0

        with gzip.open(file, 'rb') as csvfile:
            filereader = csv.reader(io.TextIOWrapper(csvfile, newline=""), delimiter='\t', quotechar='\"')
            for row in filereader:
                line_counter += 1

                if re.match('!', ''.join(row)):  # comments start with exclamation
                    continue
                (db, gene_num, gene_symbol, qualifier, go_id, ref, eco_symbol, with_or_from, aspect,
                 gene_name, gene_synonym, object_type,
                 taxon, date, assigned_by, annotation_extension, gene_product_form_id) = row

                # test for required fields
                if (db == '' or gene_num == '' or gene_symbol == '' or go_id == '' or ref == ''
                    or eco_symbol == '' or aspect == '' or object_type == '' or taxon == ''
                    or date == '' or assigned_by == ''):
                    logger.error("Missing required part of annotation on row %d:\n"+'\t'.join(row), line_counter)
                    continue

                # deal with qualifier NOT, contributes_to, colocalizes_with
                if re.search('NOT', qualifier):
                    continue

                db = self.clean_db_prefix(db)
                uniprotid = None
                gene_id = None
                if db == 'UniProtKB':
                    mapped_ids = id_map.get(gene_num)
                    if id_map is not None and mapped_ids is not None:
                        if len(mapped_ids) == 1:
                            gene_id = mapped_ids[0]
                            uniprotid = ':'.join((db, gene_num))
                            gene_num = re.sub('\w+\:', '', gene_id)
                        elif len(mapped_ids) > 1:
                            # logger.warn("Skipping gene id mapped for >1 gene %s --> %s", gene_num, str(mapped_ids))
                            continue
                    else:
                        continue
                elif db == 'MGI':
                    gene_num = re.sub('MGI:', '', gene_num)
                    gene_id = ':'.join((db, gene_num))
                    gene_id = re.sub('MGI\:MGI\:', 'MGI:', gene_id)
                else:
                    gene_id = ':'.join((db, gene_num))

                if self.testMode and not(re.match('NCBIGene', gene_id) and int(gene_num) in self.test_ids):
                    continue

                gu.addClassToGraph(g, gene_id, gene_symbol)
                if gene_name != '':
                    gu.addDescription(g, gene_id, gene_name)
                if gene_synonym != '':
                    for s in re.split('\|', gene_synonym):
                        gu.addSynonym(g, gene_id, s.strip())
                if re.search('\|', taxon):
                    # TODO add annotations with >1 taxon
                    logger.info(">1 taxon (%s) on line %d.  skipping", taxon, line_counter)
                else:
                    tax_id = re.sub('taxon:', 'NCBITaxon:', taxon)
                    geno.addTaxon(tax_id, gene_id)

                assoc = Assoc(self.name)

                assoc.set_subject(gene_id)
                assoc.set_object(go_id)

                eco_id = self.map_go_evidence_code_to_eco(eco_symbol)
                if eco_id is not None:
                    assoc.add_evidence(eco_id)

                for r in re.split('\|', ref):
                    r = r.strip()
                    if r != '':
                        prefix = re.split(':', r)[0]
                        r = re.sub(prefix, self.clean_db_prefix(prefix), r)
                        r = re.sub('MGI\:MGI\:', 'MGI:', r)
                        ref = Reference(r)
                        if re.match('PMID', r):
                            ref_type = Reference.ref_types['journal_article']
                            ref.setType(ref_type)
                        ref.addRefToGraph(g)
                        assoc.add_source(r)

                # TODO add the source of the annotations from assigned by?

                aspect_rel_map = {
                    'P': gu.object_properties['involved_in'],  # involved in
                    'F': gu.object_properties['enables'],  # enables
                    'C': gu.object_properties['part_of']  # part of
                }

                if aspect not in aspect_rel_map:
                    logger.error("Aspect not recognized: %s", aspect)

                rel = aspect_rel_map.get(aspect)
                if aspect == 'F' and re.search('contributes_to', qualifier):
                    rel = gu.object_properties['contributes_to']
                assoc.set_relationship(rel)
                if uniprotid is not None:
                    assoc.set_description('Mapped from '+uniprotid)
                # object_type should be one of:
                # protein_complex; protein; transcript; ncRNA; rRNA; tRNA; snRNA; snoRNA; any subtype of ncRNA in the Sequence Ontology. If the precise product type is unknown, gene_product should be used

                # deal with with_or_from

                # DB:gene_symbol
                # DB:gene_symbol[allele_symbol]
                # DB:gene_id
                # DB:protein_name
                # DB:sequence_id
                # GO:GO_id
                # CHEBI:CHEBI_id
                # it can identify another gene product to which the annotated gene product is similar (ISS) or interacts with (IPI)

                # worms say: WB:WBRNAi00078536|WBPhenotype:0000061  (why aren't these IMP?)
                # or InterPro:IPR001245|InterPro:IPR015015|InterPro:IPR020635

                assoc.add_association_to_graph(g)

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
            filereader = csv.reader(io.TextIOWrapper(csvfile, newline=""), delimiter='\t', quotechar='\"')
            for row in filereader:
                (uniprotkb_ac, uniprotkb_id, geneid, refseq, gi, pdb, go, uniref100, unifref90, uniref50,
                uniparc, pir, ncbitaxon, mim, unigene, pubmed, embl, embl_cds, ensembl, ensembl_trs, ensembl_pro,
                other_pubmed) = row

                if int(ncbitaxon) not in self.tax_ids:
                    continue
                if geneid.strip() != '':
                    idlist = re.split(';', geneid)
                    id_map[uniprotkb_ac.strip()] = ['NCBIGene:'+i.strip() for i in idlist]
                elif ensembl.strip() != '':
                    id_map[uniprotkb_ac.strip()] = ['ENSEMBL:'+i.strip() for i in idlist]

        logger.info("Acquired %d uniprot-entrez mappings", len(id_map))

        return id_map

    @staticmethod
    def map_go_evidence_code_to_eco(evidence_code):
        """
        The following are valid GO evidence codes and mapped to ECO, as documented here:
        http://geneontology.org/page/guide-go-evidence-codes
        :param evidence_code:
        :return:
        """

        ecotype = None
        type_map = {
            'EXP': 'ECO:0000006',
            'IBA': 'ECO:0000318',
            'IBD': 'ECO:0000319',
            'IC': 'ECO:0000001',
            'IDA': 'ECO:0000314',
            'IEA': 'ECO:0000501',
            'IEP': 'ECO:0000008',
            'IGC': 'ECO:0000317',
            'IGI': 'ECO:0000316',
            'IKR': 'ECO:0000320',
            'IMP': 'ECO:0000315',
            'IPI': 'ECO:0000353',
            'IRD': 'ECO:0000321',
            'ISA': 'ECO:0000200',
            'ISM': 'ECO:0000202',
            'ISO': 'ECO:0000201',
            'ISS': 'ECO:0000250',
            'NAS': 'ECO:0000303',
            'ND': 'ECO:0000035',
            'RCA': 'ECO:0000245',
            'TAS': 'ECO:0000304'
        }
        if evidence_code.strip() in type_map:
            ecotype = type_map.get(evidence_code)
        else:
            logger.error("Evidence code (%s) not mapped", evidence_code)

        return ecotype

    def clean_db_prefix(self, db):
        """
        Here, we map the GO-style prefixes with Monarch-style prefixes that are able to be processed by our curie_map.
        :param db:
        :return:
        """

        prefix_map = {
            'WB': 'WormBase',
            'WB_REF': 'WormBase',
            'FB': 'FlyBase',
            'Reactome': 'REACT'
        }

        clean_prefix = db
        if db in prefix_map:
            clean_prefix = prefix_map.get(db)

        return clean_prefix

    def getTestSuite(self):
        import unittest
        from tests.test_geneontology import GeneOntologyTestCase

        test_suite = unittest.TestLoader().loadTestsFromTestCase(GeneOntologyTestCase)

        return test_suite
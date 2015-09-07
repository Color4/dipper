import logging
import xml.etree.ElementTree as ET
import re
import gzip
import io
import shutil

from dipper.sources.Source import Source
from dipper.models.Dataset import Dataset
from dipper.models.assoc.G2PAssoc import G2PAssoc
from dipper.models.assoc.DispositionAssoc import DispositionAssoc
from dipper.models.Genotype import Genotype
from dipper.models.Reference import Reference
from dipper.utils.GraphUtils import GraphUtils
from dipper.sources.NCBIGene import NCBIGene
from dipper.utils.DipperUtil import DipperUtil
from dipper import curie_map


logger = logging.getLogger(__name__)


class OMIA(Source):
    """
    This is the parser for the [Online Mendelian Inheritance in Animals (OMIA)](http://www.http://omia.angis.org.au),
    from which we process inherited disorders, other (single-locus) traits, and genes in
    >200 animal species (other than human and mouse and rats).

    We generate the omia graph to include the following information:
    * genes
    * animal taxonomy, and breeds as instances of those taxa (breeds are akin to "strains" in other taxa)
    * animal diseases, along with species-specific subtypes of those diseases
    * publications (and their mapping to PMIDs, if available)
    * gene-to-phenotype associations (via an anonymous variant-locus
    * breed-to-phenotype associations

    We make links between OMIA and OMIM in two ways:
    1.  mappings between OMIA and OMIM are created as OMIA --> hasdbXref OMIM
    2.  mappings between a breed and OMIA disease are created to be a model for the mapped OMIM disease, IFF
        it is a 1:1 mapping.  there are some 1:many mappings, and these often happen if the OMIM item is a gene.

    """

    files = {
        'data': {
            'file': 'omia.xml.gz',
            'url': 'http://omia.angis.org.au/dumps/omia.xml.gz'}
    }

    def __init__(self):
        Source.__init__(self, 'omia')

        self.load_bindings()

        self.dataset = Dataset('omia', 'Online Mendelian Inheritance in Animals', 'http://omia.angis.org.au',
                               None,
                               None,
                               'http://sydney.edu.au/disclaimer.shtml')

        self.id_hash = {
            'article': {},
            'phene': {},
            'breed': {},
            'taxon': {},
            'gene': {}
        }
        self.label_hash = {}
        self.gu = GraphUtils(curie_map.get())
        self.omia_omim_map = {}   # used to store the omia to omim phene mappings

        self.test_ids = {
            'disease': ['OMIA:001702', 'OMIA:001867', 'OMIA:000478', 'OMIA:000201', 'OMIA:000810'],
            'gene': [492297, 434, 492296, 3430235, 200685834, 394659996, 200685845, 28713538, 291822383],
            'taxon': [9691, 9685, 9606, 9615, 9913, 93934, 37029, 9627, 9825],
            'breed': []  # to be filled in during parsing of breed table for lookup by breed-associations
        }

        return

    def fetch(self, is_dl_forced=False):
        """
        :param is_dl_forced:
        :return:
        """
        self.get_files(is_dl_forced)

        return

    def parse(self, limit=None):
        # names of tables to iterate - probably don't need all these:
        # Article_Breed, Article_Keyword, Article_Gene, Article_Keyword, Article_People, Article_Phene,
        # Articles, Breed, Breed_Phene, Genes_gb, Group_Categories, Group_MPO, Inherit_Type, Keywords,
        # Landmark, Lida_Links, OMIA_Group, OMIA_author, Omim_Xref, People, Phene, Phene_Gene,
        # Publishers, Resources, Species_gb, Synonyms

        self.scrub()

        if limit is not None:
            logger.info("Only parsing first %d rows", limit)

        logger.info("Parsing files...")

        if self.testOnly:
            self.testMode = True

        if self.testMode:
            self.g = self.testgraph
        else:
            self.g = self.graph
        self.geno = Genotype(self.g)

        # we do three passes through the file
        # first process species (two others reference this one)
        self.process_species(limit)

        # then, process the breeds, genes, articles, and other static stuff
        self.process_classes(limit)

        # next process the association data
        self.process_associations(limit)

        self.load_core_bindings()
        self.load_bindings()

        logger.info("Done parsing.")

        return

    def scrub(self):
        """
        The XML file seems to have mixed-encoding; we scrub out the control characters
        from the file for processing.
        :return:
        """

        logger.info("Scrubbing out the nasty characters that break our parser.")

        myfile = '/'.join((self.rawdir, self.files['data']['file']))
        tmpfile = '/'.join((self.rawdir, self.files['data']['file']+'.tmp.gz'))
        t = gzip.open(tmpfile, 'wb')
        du = DipperUtil()
        with gzip.open(myfile, 'rb') as f:
            filereader = io.TextIOWrapper(f, newline="")
            for l in filereader:
                l = du.remove_control_characters(l) + '\n'
                t.write(l.encode('utf-8'))
        t.close()

        # move the temp file
        logger.info("Replacing the original data with the scrubbed file.")
        shutil.move(tmpfile, myfile)
        return

    # ###################### XML LOOPING FUNCTIONS ##################

    def process_species(self, limit):
        """
        Loop through the xml file and process the species.  We add elements to the graph, and store the
        id-to-label in the label_hash dict.
        :param limit:
        :return:
        """

        myfile = '/'.join((self.rawdir, self.files['data']['file']))

        f = gzip.open(myfile, 'rb')
        filereader = io.TextIOWrapper(f, newline="")

        filereader.readline()  # remove the xml declaration line

        parser = ET.XMLParser(encoding='utf-8')

        for event, elem in ET.iterparse(filereader, parser=parser):
            # Species ids are == genbank species ids!
            self.process_xml_table(elem, 'Species_gb', self._process_species_table_row, limit)

        f.close()

        return

    def process_classes(self, limit):
        """
        Loop through the xml file and process the articles, breed, genes, phenes, and phenotype-grouping classes.
        We add elements to the graph, and store the id-to-label in the label_hash dict, along with the internal key-
        to-external id in the id_hash dict.  The latter are referenced in the association processing functions.

        :param limit:
        :return:
        """

        myfile = '/'.join((self.rawdir, self.files['data']['file']))

        f = gzip.open(myfile, 'rb')
        filereader = io.TextIOWrapper(f, newline="")

        filereader.readline()  # remove the xml declaration line

        parser = ET.XMLParser(encoding='utf-8')

        for event, elem in ET.iterparse(filereader, parser=parser):
            self.process_xml_table(elem, 'Articles', self._process_article_row, limit)
            self.process_xml_table(elem, 'Breed', self._process_breed_row, limit)
            self.process_xml_table(elem, 'Genes_gb', self._process_gene_row, limit)
            self.process_xml_table(elem, 'OMIA_Group', self._process_omia_group_row, limit)
            self.process_xml_table(elem, 'Phene', self._process_phene_row, limit)
            self.process_xml_table(elem, 'Omim_Xref', self._process_omia_omim_map, limit)
        f.close()

        return

    def process_associations(self, limit):
        """
        Loop through the xml file and process the article-breed, article-phene, breed-phene, phene-gene associations,
        and the external links to LIDA.

        :param limit:
        :return:
        """

        myfile = '/'.join((self.rawdir, self.files['data']['file']))

        f = gzip.open(myfile, 'rb')
        filereader = io.TextIOWrapper(f, newline="")

        filereader.readline()  # remove the xml declaration line

        parser = ET.XMLParser(encoding='utf-8')

        for event, elem in ET.iterparse(filereader, parser=parser):
            self.process_xml_table(elem, 'Article_Breed', self._process_article_breed_row, limit)
            self.process_xml_table(elem, 'Article_Phene', self._process_article_phene_row, limit)
            self.process_xml_table(elem, 'Breed_Phene', self._process_breed_phene_row, limit)
            self.process_xml_table(elem, 'Lida_Links', self._process_lida_links_row, limit)
            self.process_xml_table(elem, 'Phene_Gene', self._process_phene_gene_row, limit)

        f.close()

        return

    # ############### INDIVIDUAL TABLE-LEVEL PROCESSING FUNCTIONS ###################

    def _process_species_table_row(self, row):
        # gb_species_id, sci_name, com_name, added_by, date_modified
        tax_id = 'NCBITaxon:'+str(row['gb_species_id'])
        sci_name = row['sci_name']
        com_name = row['com_name']

        if self.testMode and (int(row['gb_species_id']) not in self.test_ids['taxon']):
            return

        self.gu.addClassToGraph(self.g, tax_id, sci_name)
        if com_name != '':
            self.gu.addSynonym(self.g, tax_id, com_name)
            self.label_hash[tax_id] = com_name  # for lookup later
        else:
            self.label_hash[tax_id] = sci_name

        return

    def _process_breed_row(self, row):

        # in test mode, keep all breeds of our test species
        if self.testMode and (int(row['gb_species_id']) not in self.test_ids['taxon']):
            return

        # save the breed keys in the test_ids for later processing
        self.test_ids['breed'] += [int(row['breed_id'])]

        breed_id = self._make_internal_id('breed', row['breed_id'])
        self.id_hash['breed'][row['breed_id']] = breed_id
        tax_id = 'NCBITaxon:'+str(row['gb_species_id'])
        breed_label = row['breed_name']
        species_label = self.label_hash.get(tax_id)
        if species_label is not None:
            breed_label = breed_label + ' ('+species_label+')'

        self.gu.addIndividualToGraph(self.g, breed_id, breed_label, tax_id)
        self.label_hash[breed_id] = breed_label

        return

    def _process_phene_row(self, row):

        phenotype_id = None
        sp_phene_label = row['phene_name']
        if sp_phene_label == '':
            sp_phene_label = None
        if 'omia_id' not in row:
            logger.info("omia_id not present for %s", row['phene_id'])
            omia_id = self._make_internal_id('phene', phenotype_id)
        else:
            omia_id = 'OMIA:'+str(row['omia_id'])

        if self.testMode and not (int(row['gb_species_id']) in self.test_ids['taxon']
                                  and omia_id in self.test_ids['disease']):
            return

        self.id_hash['phene'][row['phene_id']] = omia_id  # add to internal hash store for later lookup

        descr = row['summary']
        if descr == '':
            descr = None

        # omia label
        omia_label = self.label_hash.get(omia_id)

        # add the species-specific subclass (TODO please review this choice)
        gb_species_id = row['gb_species_id']

        if gb_species_id != '':
            sp_phene_id = '-'.join((omia_id, gb_species_id))
        else:
            logger.error("No species supplied in species-specific phene table for %s", omia_id)
            return

        species_id = 'NCBITaxon:'+str(gb_species_id)
        species_label = self.label_hash.get('NCBITaxon:'+gb_species_id)  # use this instead
        if sp_phene_label is None and omia_label is not None and species_label is not None:
            sp_phene_label = ' '.join((omia_label, 'in', species_label))
        self.gu.addClassToGraph(self.g, sp_phene_id, sp_phene_label, omia_id, descr)
        self.id_hash['phene'][row['phene_id']] = sp_phene_id  # add to internal hash store for later lookup
        self.label_hash[sp_phene_id] = sp_phene_label
        # add each of the following descriptions, if they are populated, with a tag at the end.
        for item in ['clin_feat', 'history', 'pathology', 'mol_gen']:
            if row[item] is not None and row[item] != '':
                self.gu.addDescription(self.g, sp_phene_id, row[item] + ' ['+item+']')
        # if row['symbol'] is not None:  # species-specific
        #     gu.addSynonym(g, sp_phene, row['symbol'])  # CHECK ME - sometimes spaces or gene labels

        self.gu.addOWLPropertyClassRestriction(self.g, sp_phene_id, self.gu.object_properties['in_taxon'], species_id)

        # add inheritance as an association
        inheritance_id = self._map_inheritance_term_id(row['inherit'])
        if inheritance_id is not None:
            assoc = DispositionAssoc(self.name, sp_phene_id, inheritance_id)
            assoc.add_association_to_graph(self.g)

        return

    def _process_article_row(self, row):

        # don't bother in test mode
        if self.testMode:
            return

        iarticle_id = self._make_internal_id('article', row['article_id'])
        self.id_hash['article'][row['article_id']] = iarticle_id
        rtype = None
        if row['journal'] != '':
            rtype = Reference.ref_types['journal_article']
        r = Reference(iarticle_id, rtype)

        if row['title'] is not None:
            r.setTitle(row['title'])
        if row['year'] is not None:
            r.setYear(row['year'])
        r.addRefToGraph(self.g)

        if row['pubmed_id'] is not None:
            pmid = 'PMID:'+str(row['pubmed_id'])
            self.id_hash['article'][row['article_id']] = pmid
            self.gu.addSameIndividual(self.g, iarticle_id, pmid)
            self.gu.addComment(self.g, pmid, iarticle_id)

        return

    def _process_omia_group_row(self, row):
        omia_id = 'OMIA:'+row['omia_id']

        if self.testMode and omia_id not in self.test_ids['disease']:
            return

        group_name = row['group_name']
        group_summary = row['group_summary']

        # TODO something to group category
        # group_category = row['group_category']

        if group_summary == '':
            group_summary = None
        if group_name == '':
            group_name = None
        self.gu.addClassToGraph(self.g, omia_id, group_name, None, group_summary)
        self.label_hash[omia_id] = group_name

        return

    def _process_gene_row(self, row):
        if self.testMode and row['gene_id'] not in self.test_ids['gene']:
            return
        gene_id = 'NCBIGene:'+str(row['gene_id'])
        self.id_hash['gene'][row['gene_id']] = gene_id
        gene_label = row['symbol']
        self.label_hash[gene_id] = gene_label
        tax_id = 'NCBITaxon:'+str(row['gb_species_id'])
        gene_type_id = NCBIGene.map_type_of_gene(row['gene_type'])
        self.gu.addClassToGraph(self.g, gene_id, gene_label, gene_type_id)
        self.geno.addTaxon(tax_id, gene_id)

        return

    def _process_article_breed_row(self, row):
        # article_id, breed_id, added_by
        # don't bother putting these into the test... too many!
        if self.testMode:  # and int(row['breed_id']) not in self.test_ids['breed']:
            return

        article_id = self.id_hash['article'].get(row['article_id'])
        breed_id = self._make_internal_id('breed', row['breed_id'])
        # there's some missing data (article=6038).  in that case skip
        if article_id is not None:
            self.gu.addTriple(self.g, article_id, self.gu.object_properties['is_about'], breed_id)
        else:
            logger.warn("Missing article key %s", str(row['article_id']))

        return

    def _process_article_phene_row(self, row):
        """
        Linking articles to species-specific phenes.

        :param row:
        :return:
        """
        # article_id, phene_id, added_by
        # look up the article in the hashmap
        phenotype_id = self.id_hash['phene'].get(row['phene_id'])
        article_id = self.id_hash['article'].get(row['article_id'])

        omia_id = self._get_omia_id_from_phene_id(phenotype_id)
        if self.testMode and omia_id not in self.test_ids['disease'] or phenotype_id is None or article_id is None:
            return

        # make a triple, where the article is about the phenotype
        self.gu.addTriple(self.g, article_id, self.gu.object_properties['is_about'], phenotype_id)

        return

    def _process_breed_phene_row(self, row):
        # Linking disorders/characteristic to breeds
        # breed_id, phene_id, added_by
        breed_id = self.id_hash['breed'].get(row['breed_id'])
        phene_id = self.id_hash['phene'].get(row['phene_id'])

        # get the omia id
        omia_id = self._get_omia_id_from_phene_id(phene_id)

        if self.testMode and not (omia_id in self.test_ids['disease'] and int(row['breed_id']) in self.test_ids['breed'])\
            or breed_id is None or phene_id is None:
            return

        # FIXME we want a different relationship here
        assoc = G2PAssoc(self.name, breed_id, phene_id, self.gu.object_properties['has_phenotype'])
        assoc.add_association_to_graph(self.g)

        # add that the breed is a model of the human disease
        # use the omia-omim mappings for this

        omim_ids = self.omia_omim_map.get(omia_id)
        eco_id = "ECO:0000214"   # biological aspect of descendant evidence
        if omim_ids is not None and len(omim_ids) == 1:
            # we make an assumption here that if there's only one omim id, then it is a disease;
            # if >1 we assume it might be a gene; but we should verify this
            # perhaps use the omim services rest api to figure it out.
            for i in omim_ids:
                assoc = G2PAssoc(self.name, breed_id, i, self.gu.object_properties['model_of'])
                assoc.add_evidence(eco_id)
                assoc.add_association_to_graph(self.g)
                aid = assoc.get_association_id()

                breed_label = self.label_hash.get(breed_id)
                if breed_label is None:
                    breed_label = "this breed"

                m = re.search('\((.*)\)', breed_label)
                if m:
                    sp_label = m.group(1)
                else:
                    sp_label = ''

                phene_label = self.label_hash.get(phene_id)
                if phene_label is None:
                    phene_label = "phenotype"
                elif phene_label.endswith(sp_label):
                    # some of the labels we made include the species in it already; remove it to make a cleaner desc
                    phene_label = re.sub(' in '+sp_label, '', phene_label)
                desc = ' '.join(("High incidence of", phene_label, "in",
                                 breed_label, "suggests it to be a model of disease", i+"."))
                self.gu.addDescription(self.g, aid, desc)
        return

    def _process_lida_links_row(self, row):
        # lidaurl, omia_id, added_by
        omia_id = 'OMIA:'+row['omia_id']
        lidaurl = row['lidaurl']

        if self.testMode and omia_id not in self.test_ids['disease']:
            return

        self.gu.addXref(self.g, omia_id, lidaurl, True)

        return

    def _process_phene_gene_row(self, row):

        gene_id = self.id_hash['gene'].get(row['gene_id'])
        phene_id = self.id_hash['phene'].get(row['phene_id'])

        omia_id = self._get_omia_id_from_phene_id(phene_id)

        if self.testMode and not (omia_id in self.test_ids['disease'] and row['gene_id'] in self.test_ids['gene'])\
           or gene_id is None or phene_id is None:
            return

        # occasionally some phenes are missing!  (ex: 406)
        if phene_id is None:
            logger.warn("Phene id %s is missing", str(row['phene_id']))
            return

        gene_label = self.label_hash[gene_id]
        # some variant of gene_id has phenotype d
        vl = '_'+re.sub('NCBIGene:', '', str(gene_id)) + 'VL'
        if self.nobnodes:
            vl = ':'+vl
        self.geno.addAllele(vl, 'some variant of ' + gene_label)
        self.geno.addAlleleOfGene(vl, gene_id)
        assoc = G2PAssoc(self.name, vl, phene_id)
        assoc.add_association_to_graph(self.g)

        return

    def _process_omia_omim_map(self, row):
        """
        Links OMIA groups to OMIM equivalents.
        :param row:
        :return:
        """
        # omia_id, omim_id, added_by

        omia_id = 'OMIA:'+row['omia_id']
        omim_id = 'OMIM:'+row['omim_id']

        if self.testMode and omia_id not in self.test_ids['disease']:
            return

        self.gu.addXref(self.g, omia_id, omim_id)
        # also store this for use when we say that a given animal is a model of a disease
        if omia_id not in self.omia_omim_map:
            self.omia_omim_map[omia_id] = set()
        self.omia_omim_map[omia_id].add(omim_id)

        return

    def _make_internal_id(self, prefix, key):

        iid = '_'+''.join(('omia', prefix, 'key', str(key)))
        if self.nobnodes:
            iid = ':'+iid

        return iid

    @staticmethod
    def _get_omia_id_from_phene_id(phene_id):
        omia_id = None
        if phene_id is not None:
            m = re.match('OMIA:\d+', str(phene_id))
            if m:
                omia_id = m.group(0)

        return omia_id

    def _map_inheritance_term_id(self, inheritance_symbol):

        inheritance_id = None

        inherit_map = {
            'A':  None,  # Autosomal
            'ACD': 'GENO:0000143',  # Autosomal co-dominant
            'ADV': None,  # autosomal dominant with variable expressivity
            'AID': 'GENO:0000259',  # autosomal incompletely dominant
            'ASD': 'GENO:0000145',  # autosomal semi-dominant
            'ASL': 'GENO:0000150',  # autosomal recessive, semi-lethal  <-- using generic autosomal recessive
            'D': 'GENO:0000147',  # autosomal dominant
            'M': None,  # multifactorial
            'MAT': None,  # Maternal
            'PR':  'GENO:0000150',  # probably autosomal recessive  <-- using generic autosomal recessive
            'R': 'GENO:0000150',  # Autosomal Recessive
            'REL': 'GENO:0000148',  #Recessive Embryonic Lethal   <-- using plain recessive
            'RL': 'GENO:0000150', # Autosomal Recessive Lethal  <-- using plain autosomal recessive
            'S': 'GENO:0000146',  # Sex-linked   <--using allosomal dominant
            'SLi': None,  # Sex-limited
            'UD': 'GENO:0000144',  #Dominant
            'X': None,  # x-linked    # HP:0001417
            'XLD': 'GENO:0000146',  # X-linked Dominant     <-- temp using allosomal dominant  FIXME
            'XLR': 'GENO:0000149',  # X-linked Recessive    <-- temp using allosomal recessive  FIXME
            'Y': None, # Y-linked
            'Z': None, # Z-linked
            'ZR': 'GENO:0000149',  # Z-linked recessive    <-- temp using allosomal recessive  FIXME
            '999': None,  # Z-linked incompletely dominant
        }

        inheritance_id = inherit_map.get(inheritance_symbol)
        if inheritance_id is None and inheritance_symbol is not None:
            logger.warn("No inheritance id is mapped for %s", inheritance_symbol)

        return inheritance_id

    def getTestSuite(self):
        import unittest
        from tests.test_omia import OMIATestCase

        test_suite = unittest.TestLoader().loadTestsFromTestCase(OMIATestCase)

        return test_suite

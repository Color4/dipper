import logging
import csv
import pysftp

from dipper.sources.Source import Source
from dipper.models.Assoc import Assoc
from dipper.models.Dataset import Dataset
from dipper import config
from dipper.utils.GraphUtils import GraphUtils
from dipper import curie_map




logger = logging.getLogger(__name__)

class Coriell(Source):
    """
    The Coriell Catalog provided to Monarch includes metadata and descriptions of NIGMS, NINDS, NHGRI, and
    NIA cell lines.  These lines are made available for research purposes.
    Here, we create annotations for the cell lines as models of the diseases from which
    they originate.

    Notice: The Coriell catalog is delivered to Monarch in a specific format, and requires ssh rsa fingerprint
    identification.  Other groups wishing to get this data in it's raw form will need to contact Coriell
    for credentials.

    """

    terms = {
        'sampling_time': 'EFO:0000689',
        'human': 'NCBITaxon:9606',
        'in_taxon': 'RO:0002162',
        'cell_line_repository': 'CLO:0000008',
        'race': 'SIO:001015',
        'ethnic_group': 'EFO:0001799',
        'mentions': 'IAO:0000142'
    }




    files = {
        'ninds': {'file' : 'NINDS_2014-02-03_13-32-24.csv',
                  'id' : 'NINDS',
                  'label': 'NINDS Human Genetics DNA and Cell line Repository',
                  'page' : 'https://catalog.coriell.org/1/NINDS'},
        'nigms': {'file' : 'NIGMS_2014-02-03_13-31-42.csv',
                  'id' : 'NIGMS',
                  'label': 'NIGMS Human Genetic Cell Repository',
                  'page' : 'https://catalog.coriell.org/1/NIGMS'},
        'nia': {'file' : 'NIA_2015-02-20_16-08-04.csv',
                'id' : 'NIA',
                'label': 'NIA Aging Cell Repository',
                'page': 'https://catalog.coriell.org/1/NIA'}
    }



    def __init__(self):
        Source.__init__(self, 'coriell')

        self.load_bindings()

        self.dataset = Dataset('coriell', 'Coriell', 'http://ccr.coriell.org/nigms/')

        #data-source specific warnings (will be removed when issues are cleared)
        #print()

        #check if config exists; if it doesn't, error out and let user know
        if (not (('keys' in config.get_config()) and ('coriell' in config.get_config()['keys']))):
            logger.error("ERROR: not configured with FTP user/password.")
        return


    def fetch(self, is_dl_forced):
        """
        Be sure to have pg user/password connection details in your conf.json file, like:
        dbauth : {
        "coriell" : {"user" : "<username>", "password" : "<password>", "host" : <host>}
        }

        :param is_dl_forced:
        :return:
        """
        host1 = config.get_config()['keys']['coriell']['host']
        user1 = 'username=\''+ config.get_config()['keys']['coriell']['user']+'\''
        passwd1 = 'password=\''+ config.get_config()['keys']['coriell']['password']+'\''
        #print(host1,user1,passwd1)
        #ftp = FTP(config.get_config()['keys']['coriell']['host'],config.get_config()['keys']['coriell']['user'],config.get_config()['keys']['coriell']['password'],timeout=None)
        #ftp = FTP(host1,user1,passwd1,timeout=None)
        #ftp.login()

        #with pysftp.Connection(host1, user1, passwd1) as sftp:
            #with sftp.cd('public')
            #print('success!')
                #sftp.get_r()


        return

    def scrub(self):
        '''
        Perform various data-scrubbing on the raw data files prior to parsing.
        For this resource, this currently includes:

        :return: None
        '''
        # scrub file of the oddities where there are "\" instead of empty strings
        #pysed.replace("\r", '', ('/').join((self.rawdir,'dv.nlx_157874_1')))

        return

    def parse(self, limit=None):
        if (limit is not None):
            logger.info("Only parsing first %s rows of each file", limit)

        logger.info("Parsing files...")

        for f in ['ninds','nigms','nia']:
            file = ('/').join((self.rawdir,self.files[f]['file']))
            self._process_repository(self.files[f]['id'],self.files[f]['label'],self.files[f]['page'])
            self._process_data(file, limit)

        logger.info("Finished parsing.")


        self.load_bindings()
        Assoc().loadObjectProperties(self.graph)

        logger.info("Found %s nodes", len(self.graph))
        return

    def _process_data(self, raw, limit=None):
        """
        This function will process the data files from Coriell.



        Triples: (examples)

            :NIGMSrepository a CLO_0000008 #repository  ?
                label : NIGMS Human Genetic Cell Repository
                foaf:page https://catalog.coriell.org/0/sections/collections/NIGMS/?SsId=8

            line_id a CL_0000057,  #fibroblast line
                derives_from patient_id, uberon:Fibroblast
                part_of :NIGMSrepository
                #we also have the age_at_sampling type of property

            patient id a foaf:person, proband, OMIM:disease_id
                label: "fibroblast from patient 12345 with disease X"
                member_of family_id  #what is the right thing here?
                SIO:race EFO:caucasian  #subclass of EFO:0001799
                in_taxon NCBITaxon:9606
                dc:description Literal(remark)
                GENO:has_genotype genotype_id

            family_id a owl:NamedIndividual
                foaf:page "https://catalog.coriell.org/0/Sections/BrowseCatalog/FamilyTypeSubDetail.aspx?PgId=402&fam=2104&coll=GM"

            genotype_id a intrinsic_genotype
                GENO:has_variant_part allelic_variant_id
                #we don't necessarily know much about the genotype, other than the allelic variant.
                #also there's the sex here)

            pub_id mentions cell_line_id



        :param raw:
        :param limit:
        :return:
        """
        logger.info("Processing Data from %s",raw)
        gu = GraphUtils(curie_map.get())

        line_counter = 0
        with open(raw, 'r', encoding="iso-8859-1") as csvfile:
            filereader = csv.reader(csvfile, delimiter=',', quotechar='\"')
            next(filereader, None)  # skip the header row
            for row in filereader:
                if not row:
                    pass
                else:
                    line_counter += 1

                    (catalog_id,description,omim_number,sample_type,cell_line_available,
                    dna_in_stock,dna_ref,gender,age,race,ethnicity,affected,karyotype,
                    relprob,mutation,gene,family_id,collection,url,cat_remark,pubmed_ids) = row



                    ##############    BUILD REQUIRED VARIABLES    #############

                    #Make the cell line ID
                    cell_line_id = 'Coriell:'+catalog_id.strip()

                    #Map the cell/sample type
                    cell_type = self._map_cell_type(sample_type)

                    #Make a cell line label
                    #FIXME:Including a generic label for now.
                    line_label = collection.partition(' ')[0]+'-'+catalog_id.strip()

                    #Map the repository/collection
                    repository = self._map_collection(collection)

                    #Make the patient ID
                    # FIXME: Need a better patient ID from Coriell.
                    if family_id != '':
                        #patient_id = self.make_id(family_id+relprob)
                        patient_id = self.make_id(cell_line_id)
                    else:
                        #FIXME: Adjust this?
                        #Think it would be better just to make an id
                        patient_id = self.make_id(cell_line_id)

                    #Make a label for the patient
                    patient_label = sample_type+' from patient '+patient_id+' with '+description


                    ##############    BUILD THE CELL LINE    #############

                    # Adding the cell line as a typed individual.
                    gu.addIndividualToGraph(self.graph,cell_line_id,line_label,cell_type)

                    #TODO: Do we need to map the cell types to Uberon, or does the fact that we have mapped to CL
                    # mean that the mapping is performed at the ontology level? Also, many of the matching terms
                    # are marked as obsolete in Uberon.

                    # Cell line derives from patient
                    # Should we call this from the Genotype.py or generalize to the GraphUtils?
                    rel = gu.getNode(gu.relationships['derives_from'])
                    self.graph.add((gu.getNode(cell_line_id), rel, gu.getNode(patient_id)))

                    # Cell line part_of repository
                    rel = gu.getNode(gu.relationships['part_of'])
                    self.graph.add((gu.getNode(cell_line_id), rel, gu.getNode(repository)))

                    # Cell age_at_sampling
                    #FIXME: More appropriate term than sampling_time?
                    gu.addTriple(self.graph,patient_id,self.terms['sampling_time'],age,object_is_literal=True)


                    ##############    BUILD THE PATIENT    #############

                    # Add the patient ID as an individual.
                    #FIXME: How to add FOAF:Person?
                    # Do we need to add the person as a 'Category' instead of a class or individual?
                    #gu.addClassToGraph(self.graph,patient_id,patient_label)
                    #gu.addIndividualToGraph(self.graph,patient_id,patient_label,(FOAF['person']))

                    #Add the patient as a person with label.
                    gu.addPerson(self.graph,patient_id,patient_label)

                    #Add proband as type to patient
                    gu.addType(self.graph,patient_id,relprob,type_is_literal=True)

                    #TODO: OMIM Disease
                    # Add OMIM Disease ID (';' delimited)
                    #Perhaps add OMIM ID, and if no OMIM ID is present, just add a disease description?
                    #Assuming we don't need a disease description if it has an OMIM ID, as that can be mapped from OMIM.
                    #FIXME: Don't believe this adding as type is correct.
                    if omim_number != '':
                        for s in omim_number.split(';'):
                            disease_id = 'OMIM:'+s.strip()
                            gu.addType(self.graph,patient_id,disease_id)
                            #self.graph.add((n, RDF['type'], ))

                    # Add taxon to patient
                    gu.addTriple(self.graph,patient_id,self.terms['mentions'],self.terms['human'])

                    # Add sex/gender of patient?
                    # Add affected status?
                    #Add

                    # Add description (remark) to patient
                    if cat_remark !='':
                        gu.addDescription(self.graph,patient_id,cat_remark)

                    # Add race of patient
                    #FIXME: Adjust for subcategories based on ethnicity field
                    #EDIT: There are 743 different entries for ethnicity... Too many to map
                    #Perhaps add ethnicity as a literal in addition to the mapped race?
                    #Need to adjust the ethnicity text to just initial capitalization as some entries:ALL CAPS
                    if race != '':
                        mapped_race = self._map_race(race)
                        if mapped_race is not None:
                            gu.addTriple(self.graph,patient_id,self.terms['race'],mapped_race)
                            gu.addSubclass(self.graph,self.terms['ethnic_group'],mapped_race)


                    #TODO: Need genotype data, not currently available.
                    #Can build some rudimentary info from what's in the data set:

                    ##############    BUILD THE FAMILY    #############

                    # Add triples for family_id, if present.
                    #FIXME: Is this the correct approach for the family ID URI?
                    #Once the CoriellFamily: prefix is resolved through the curie map,
                    # then family_comp_id = family_url.
                    if family_id != '':
                        family_comp_id = 'CoriellFamily:'+family_id

                        # Add the family ID as a named individual
                        gu.addIndividualToGraph(self.graph,family_comp_id,None)

                        #Add the patient as a member of the family
                        gu.addMemberOf(self.graph,patient_id,family_comp_id)

                        #set URL for family_id
                        family_url = 'https://catalog.coriell.org/0/Sections/BrowseCatalog/FamilyTypeSubDetail.aspx?fam='+family_id

                        #Add family URL as page to family_id.
                        gu.addPage(self.graph,family_comp_id,family_url)





                    if pubmed_ids != '':
                        for s in pubmed_ids.split(';'):
                            pubmed_id = 'PMID:'+s.strip()
                            gu.addTriple(self.graph,pubmed_id,self.terms['mentions'],cell_line_id)
                            #gu.addSynonym(self.graph,morphology_term_id,s.strip(), gu.relationships['hasRelatedSynonym'])



                    if (limit is not None and line_counter > limit):
                        break
        return

    def _process_repository(self, id, label, page):
        """
        This function will process the data supplied internally about the repository from Coriell.

        Triples:
            Repository a CLO_0000008 #repository
            rdf:label Literal (label)
            foaf:page Literal (page)


        :param raw:
        :param limit:
        :return:
        """
        ##############    BUILD THE CELL LINE REPOSITORY    #############
        #FIXME: How to devise a label for each repository?
        gu = GraphUtils(curie_map.get())
        repo_id = 'CoriellCollection:'+id
        repo_label = label
        repo_page = page
        #gu.addClassToGraph(self.graph,repo_id,repo_label)
        gu.addIndividualToGraph(self.graph,repo_id,repo_label,self.terms['cell_line_repository'])
        gu.addPage(self.graph,repo_id,repo_page)

        return



    def _map_cell_type(self, sample_type):
        type = None
        type_map = {
            'Adipose stromal cell': 'CL:0002570', # FIXME: mesenchymal stem cell of adipose
            'Amniotic fluid-derived cell line': 'CL:0002323',  # FIXME: amniocyte?
            'B-Lymphocyte': 'CL:0000236',  # B cell
            'Chorionic villus-derived cell line': 'CL:0000000', # FIXME: No Match
            'Endothelial': 'CL:0000115',  # endothelial cell
            'Epithelial': 'CL:0000066',  # epithelial cell
            'Erythroleukemic cell line': 'CL:0000000',  # FIXME: No Match. "Abnormal precursor (virally transformed) of mouse erythrocytes that can be grown in culture and induced to differentiate by treatment with, for example, DMSO."
            'Fibroblast': 'CL:0000057',  # fibroblast
            'Keratinocyte': 'CL:0000312', # keratinocyte
            'Melanocyte': 'CL:0000148',  # melanocyte
            'Mesothelial': 'CL:0000077',
            'Microcell hybrid': 'CL:0000000',  # FIXME: No Match
            'Myoblast': 'CL:0000056',  # myoblast
            'Smooth muscle': 'CL:0000192',  # smooth muscle cell
            'Stem cell': 'CL:0000034',  # stem cell
            'T-Lymphocyte': 'CL:0000084',  # T cell
            'Tumor-derived cell line': 'CL:0002198'  # FIXME: No Match. "Cells isolated from a mass of neoplastic cells, i.e., a growth formed by abnormal cellular proliferation." Oncocyte? CL:0002198
        }
        if (sample_type.strip() in type_map):
            type = type_map.get(sample_type)
        else:
            logger.warn("ERROR: Cell type not mapped: %s", sample_type)

        return type


    def _map_race(self, race):
        type = None
        type_map = {
            'African American': 'EFO:0003150',
            #'American Indian': 'EFO',
            'Asian': 'EFO:0003152',
            'Asian; Other': 'EFO:0003152',  # FIXME: Asian?
            'Asiatic Indian': 'EFO:0003153',  # Asian Indian
            'Black': 'EFO:0003150',  # FIXME: African American? There is also African.
            'Caucasian': 'EFO:0003156',
            'Chinese': 'EFO:0003157',
            'East Indian': 'EFO:0003158',  # Eastern Indian
            'Filipino': 'EFO:0003160',
            'Hispanic/Latino': 'EFO:0003169',  # Hispanic: EFO:0003169, Latino: EFO:0003166
            'Japanese': 'EFO:0003164',
            'Korean': 'EFO:0003165',
            #'More than one race': 'EFO',
            #'Not Reported': 'EFO',
            #'Other': 'EFO',
            'Pacific Islander': 'EFO:0003154',  # Asian/Pacific Islander
            'Polynesian': 'EFO:0003154',  # Asian/Pacific Islander
            #'Unknown': 'EFO',
            'Vietnamese': 'EFO:0003152',  # Asian
        }
        if (race.strip() in type_map):
            type = type_map.get(race)
        else:
            logger.warn("Race type not mapped: %s", race)

        return type

    def _map_collection(self, collection):
        type = None
        type_map = {
            'NINDS Repository': 'CoriellCollection:NINDS',
            'NIGMS Human Genetic Cell Repository': 'CoriellCollection:NIGMS',
            'NIA Aging Cell Culture Repository': 'CoriellCollection:NIA'
        }
        if (collection.strip() in type_map):
            type = type_map.get(collection)
        else:
            logger.warn("ERROR: Collection type not mapped: %s", collection)

        return type
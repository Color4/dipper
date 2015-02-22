import os
from datetime import datetime
from stat import *
import re
import logging


from rdflib import Literal
from rdflib.namespace import DC, FOAF
from rdflib import URIRef

from sources.Source import Source
from models.Assoc import Assoc
from models.Dataset import Dataset
from utils.CurieUtil import CurieUtil
from conf import config, curie_map
from utils.GraphUtils import GraphUtils

logger = logging.getLogger(__name__)

class EOM(Source):
    """
    Elements of Morphology is a great resource from NHGRI that has definitions of morphological abnormalities,
    together with image depictions.  We pull those relationships, as well as our local mapping of equivalences
    between EOM and HP terminologies.

    The website is crawled monthly by NIF's DISCO crawler system, which we utilize here.
    Be sure to have pg user/password connection details in your conf.json file, like:
      dbauth : {
        'disco' : {'user' : '<username>', 'password' : '<password>'}
      }

    Hand-curated data for the HP to EOM mapping is currently stored offline, and will need to be placed into
    the raw/ directory here.  TODO: move this into a public repo.

    """

    #we are using the dv view here; i wonder if we should be using the prod view, or their services instead.?
    tables = [
        'dv.nlx_157874_1'
    ]


    relationship = {
        'hasRelatedSynonym': 'OIO:hasRelatedSynonym',
    }


    def __init__(self):
        Source.__init__(self, 'eom')
        self.namespaces.update(curie_map.get())

        #update the dataset object with details about this resource
        #TODO put this into a conf file?
        self.dataset = Dataset('eom', 'EOM', 'http://elementsofmorphology.nih.gov')

        #check if config exists; if it doesn't, error out and let user know
        if (not (('dbauth' in config.get_config()) and ('disco' in config.get_config()['dbauth']))):
            logger.error("ERROR: not configured with PG user/password.")

        #source-specific warnings.  will be cleared when resolved.

        return


    def fetch(self, is_dl_forced):

        #create the connection details for DISCO
        cxn = config.get_config()['dbauth']['disco']
        cxn.update({'host' : 'nif-db.crbs.ucsd.edu', 'database' : 'disco_crawler', 'port' : 5432 })

        self.dataset.setFileAccessUrl(('').join(('jdbc:postgresql://',cxn['host'],':',str(cxn['port']),'/',cxn['database'])))

        #process the tables
        #self.fetch_from_pgdb(self.tables,cxn,100)  #for testing
        self.fetch_from_pgdb(self.tables,cxn)


        #FIXME: Everything needed for data provenance?
        st = os.stat(('/').join((self.rawdir,'dv.nlx_157874_1')))
        filedate=datetime.utcfromtimestamp(st[ST_CTIME]).strftime("%Y-%m-%d")
        self.dataset.setVersion(filedate)




        return


    def parse(self, limit=None):
        if (limit is not None):
            logger.info("Only parsing first %s rows of each file", limit)

        logger.info("Parsing files...")

        self._process_nlx_157874_1_view(('/').join((self.rawdir,'dv.nlx_157874_1')),limit)
        self._map_eom_terms(('/').join((self.rawdir,'eom_terms.tsv')),limit)

        logger.info("Finished parsing.")


        self.load_bindings()
        Assoc().loadObjectProperties(self.graph)

        logger.info("Found %s nodes", len(self.graph))
        return



    def _process_nlx_157874_1_view(self, raw, limit=None):
        """
        This table contains the Elements of Morphology data that has been screen-scraped into DISCO.
        Note that foaf:depiction is inverse of foaf:depicts relationship.

        Triples:
            <eom id> a owl:Class
                rdf:label Literal(eom label)
                OIO:hasRelatedSynonym Literal(synonym list)
                IAO:definition Literal(subjective def), Literal(objective_def)
                foaf:depiction Literal(small_image_url),Literal(large_image_url)
                foaf:page Literal(page_url)
                dc:comment Literal(long commented text)


        :param raw:
        :param limit:
        :return:
        """

        gu = GraphUtils(curie_map.get())
        line_counter = 0
        with open(raw, 'r') as f1:
            f1.readline()  # read the header row; skip
            for line in f1:
                line_counter += 1

                (morphology_term_id, morphology_term_num, morphology_term_label, morphology_term_url,
                 terminology_category_label, terminology_category_url, subcategory, objective_definition,
                 subjective_definition, comments, synonyms, replaces, small_figure_url, large_figure_url,
                 e_uid, v_uid, v_uuid, v_last_modified) = line.split('\t')

                #Add morphology term to graph as a class with label, type, and description.
                gu.addClassToGraph(self.graph,morphology_term_id,morphology_term_label)

                #Assemble the description text
                description = None
                if subjective_definition.strip() != '':
                    subjective_definition = 'Subjective Description: '+subjective_definition.strip()
                    gu.addDefinition(self.graph,morphology_term_id,subjective_definition)
                if objective_definition.strip() != '':
                    objective_definition = 'Objective Description: '+objective_definition.strip()
                    gu.addDefinition(self.graph,morphology_term_id,objective_definition)


                #<term id> FOAF:depicted_by literal url
                #<url> type foaf:depiction

                #do we want both images?
                #morphology_term_id has depiction small_figure_url
                if small_figure_url != '':
                    gu.addDepiction(self.graph,morphology_term_id,small_figure_url)

                #morphology_term_id has depiction large_figure_url
                if large_figure_url != '':
                    gu.addDepiction(self.graph,morphology_term_id,large_figure_url)

                #morphology_term_id has comment comments
                if comments != '':
                    gu.addComment(self.graph,morphology_term_id,comments.strip())


                if synonyms != '':
                    for s in synonyms.split(';'):
                        gu.addSynonym(self.graph,morphology_term_id,s.strip())

                #morphology_term_id hasRelatedSynonym replaces (; delimited)
                if replaces != '' and replaces != synonyms:
                    for s in replaces.split(';'):
                        gu.addSynonym(self.graph,morphology_term_id,s.strip())

                #morphology_term_id has page morphology_term_url
                gu.addPage(self.graph,morphology_term_id,morphology_term_url)

                if (limit is not None and line_counter > limit):
                    break
        return

    def _map_eom_terms(self, raw, limit=None):
        """
        This table contains the HP ID mappings from the local tsv file.
        Triples:
            <eom id> owl:equivalentClass <hp id>
        :param raw:
        :param limit:
        :return:
        """

        gu = GraphUtils(curie_map.get())

        line_counter = 0
        with open(raw, 'r') as f1:
            f1.readline()  # read the header row; skip
            for line in f1:
                line_counter += 1

                (morphology_term_id, morphology_term_label, hp_id, hp_label,notes) = line.split('\t')

                #Sub out the underscores for colons.
                hp_id = re.sub('_', ':', hp_id)
                if re.match(".*HP:.*", hp_id):
                    #add the HP term as a class
                    gu.addClassToGraph(self.graph,hp_id,None)
                    #Add the HP ID as an equivalent class
                    gu.addEquivalentClass(self.graph,morphology_term_id,hp_id)
                else:
                    logger.warning('No matching HP term for %s',morphology_term_label)

                if (limit is not None and line_counter > limit):
                    break

        return



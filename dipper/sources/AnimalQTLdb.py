import csv
import logging
import re

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
        'Bos_taurus': {'file': 'QTL_Btau_4.6.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_Btau_4.6.gff.txt.gz'},
        'UMD': {'file': 'QTL_UMD_3.1.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_UMD_3.1.gff.txt.gz'},
        'gallus_gallus': {'file': 'QTL_GG_4.0.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_GG_4.0.gff.txt.gz'},
        'sus_scrofa': {'file': 'QTL_SS_10.2.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_SS_10.2.gff.txt.gz'},
        'OAR': {'file': 'QTL_OAR_3.1.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_OAR_3.1.gff.txt.gz'},
        'EquCab': {'file': 'QTL_EquCab2.0.gff.txt.gz',
                 'url': 'http://www.animalgenome.org/QTLdb/tmp/QTL_EquCab2.0.gff.txt.gz'}
    }

#CM files
#http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/rainbow_trout_QTLdata.txt
#http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/cattle_QTLdata.txt
#http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/chicken_QTLdata.txt
#http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/pig_QTLdata.txt
#http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/rainbow_trout_QTLdata.txt
#http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/sheep_QTLdata.txt
#http://www.animalgenome.org/QTLdb/export/KSUI8GFHOT6/horse_QTLdata.txt


    # I do not love putting these here; but I don't know where else to put them
    test_ids = {
    }

    def __init__(self):
        Source.__init__(self, 'animalqtldb')

        # update the dataset object with details about this resource
        # TODO put this into a conf file?
        self.dataset = Dataset('animalqtldb', 'Animal QTL db', 'http://www.genome.jp/kegg/', None, None)

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


        logger.info("Finished parsing")

        self.load_bindings()

        logger.info("Found %d nodes", len(self.graph))
        return


#first-pass with dipper
#this will eventually control the processing of data sources
__author__ = 'nlw'

import config
import argparse
from sources.HPOAnnotations import HPOAnnotations
from sources.ZFIN import ZFIN
from sources.OMIM import OMIM
from sources.BioGrid import BioGrid
from sources.MGI import MGI
from sources.IMPC import IMPC
from sources.Panther import Panther
from sources.NCBIGene import NCBIGene
from sources.UCSCBands import UCSCBands

source_to_class_map={
    'hpoa' : HPOAnnotations, # ~3 min
    'zfin' : ZFIN,
    'omim' : OMIM,  #full file takes ~15 min, due to required throttling
    'biogrid' : BioGrid,  #interactions file takes <10 minutes
    'mgi' : MGI,
    'impc' : IMPC,
    'panther' : Panther,  #this takes a very long time, ~1hr to map 7 species-worth of associations
    'ncbigene' : NCBIGene,  #takes about 4 minutes to process 2 species
    'ucscbands' : UCSCBands
}


#TODO command-line args:
# *force re-download
# *specify the source
# *parse only without writing
# *parse only X lines of original file
# *quiet mode (with proper logging methods)

parser = argparse.ArgumentParser(description='Dipper: Data Ingestion'
                                             ' Pipeline for SciGraph')
parser.add_argument('--sources', type=str, help='comma separated list'
                                                ' of sources')
parser.add_argument('--limit', type=int, help='limit number of rows')
parser.add_argument('--parse_only', action='store_true',
                    help='parse files without writing')
args = parser.parse_args()

#iterate through all the sources
for source in args.sources.split(','):
    print()
    print("*******", source, "*******")
    source = source.lower()
    mysource = source_to_class_map[source]()
    mysource.parse(args.limit)
    if args.parse_only is False:
        mysource.write(format='turtle')
    #status = mysource.verify()
#    if status is not True:
#        print('ERROR: Source',source,'did not pass verification tests.')
#    print('***** Finished with',source,'*****')


#load configuration parameters
#for example, keys

print("All done.")


###########################




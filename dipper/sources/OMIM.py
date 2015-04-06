import os
from stat import *
import urllib
from urllib import request
import re
import time
from datetime import datetime
import os.path
import json
from subprocess import call


from dipper.sources.Source import Source
from dipper.models.Dataset import Dataset
from dipper.models.G2PAssoc import G2PAssoc
from dipper.models.Genotype import Genotype
from dipper.models.GenomicFeature import Feature,makeChromID,makeChromLabel
from dipper.utils.GraphUtils import GraphUtils
from dipper import config
from dipper import curie_map
from dipper.utils.romanplus import romanNumeralPattern,fromRoman, toRoman


class OMIM(Source):
    """
     OMIM is an unusual source.  We can get lots of the disease-gene associations, including allelic variants
     from their ftp site, which is obtainable anonymously.  However, more detailed information is available
     via their API.  So, we pull the basic files from their ftp site, extract the omim identifiers,
     then query their API in batch.  (Note this requires an apiKey, which is not stored in the repo,
     but in a separate conf.json file.)
     Processing this source serves two purposes:
     1.  enables the creation of the OMIM classes for the purposes of merging into the disease ontology
     2.  adds annotations such as disease-gene associations

     When creating the disease classes, we pull from their REST-api id/label/definition information.
     Additionally we pull the Orphanet and UMLS mappings (to make equivalent ids).  We also pull the
     phenotypic series annotations as grouping classes.

     Note that
    """

    files = {
        'all' : {
            'file' : 'omim.txt.Z',
            'url' : 'ftp://anonymous:info%40monarchinitiative.org@ftp.omim.org/OMIM/omim.txt.Z'
        },
        #'genemap' : {
        #    'file': 'genemap.txt',
        #    'url' : 'ftp://anonymous:info%40monarchinitiative.org@ftp.omim.org/OMIM/genemap'
        #},
        #'genemapkey' : {
        #    'file': 'genemapkey.txt',
        #    'url' : 'ftp://anonymous:info%40monarchinitiative.org@ftp.omim.org/OMIM/genemap.key'
        #},
        'morbidmap' : {
           'file': 'morbidmap.txt',
            'url' : 'ftp://anonymous:info%40monarchinitiative.org@ftp.omim.org/OMIM/morbidmap'
        },
        'phenotypicSeries' : {
            'file' : 'phenotypicSeriesTitles.txt',
            'url' : 'http://www.omim.org/phenotypicSeriesTitle/all?format=tab'
        }

    }

    test_ids = [
        119600,120160,157140,158900,166220,168600,219700,253250,305900,600669,601278,602421,605073,607822, #from coriell
        102560,102480,100678,102750,                     #genes
        104200,105400,114480,115300,121900,              #phenotype/disease -- indicate that here?
        107670,11600,126453,                             #gene of known sequence and has a phenotype
        102150,104000,107200,100070]                     #disease with known locus

    OMIM_API = "http://api.omim.org/api"

    def __init__(self):
        Source.__init__(self, 'omim')

        self.load_bindings()

        self.dataset = Dataset('omim', 'Online Mendelian Inheritance in Man', 'http://www.omim.org')

        #data-source specific warnings (will be removed when issues are cleared)
        #print()

        #check if config exists; if it doesn't, error out and let user know
        if (not (('keys' in config.get_config()) and ('omim' in config.get_config()['keys']))):
            print("ERROR: not configured with API key.")

        if (not (('test_ids' in config.get_config()) and ('disease' in config.get_config()['test_ids']))):
            print("WARN: not configured with disease test ids.")
        else:
            #select ony those test ids that are omim's.
            self.test_ids += [obj.replace('OMIM:','') for obj in config.get_config()['test_ids']['disease'] if re.match('OMIM:',obj)]

        return

    def fetch(self, is_dl_forced):
        #this is fetching the standard files, not from the API/REST service
        for f in self.files.keys():
            file = self.files.get(f)
            self.fetch_from_url(file['url'],
                                ('/').join((self.rawdir,file['file'])),
                                is_dl_forced)
            self.dataset.setFileAccessUrl(file['url'])
            st = os.stat(('/').join((self.rawdir,file['file'])))

        filedate=datetime.utcfromtimestamp(st[ST_CTIME]).strftime("%Y-%m-%d")

        self.dataset.setVersion(filedate)

        return


    def parse(self, limit=None):
        if (limit is not None):
            print("Only parsing first", limit, "rows")

        print("Parsing files...")

        #do each; once in test mode, the other in regular mode
        for test in [True,False]:
            self._process_all(limit,test)
            self._process_morbidmap(limit,test)
            self._process_phenotypicseries(limit,test)

        self.load_core_bindings()
        self.load_bindings()


        print("Done parsing.")


        return


    def _get_omim_ids(self):
        omimids = []

        #an omim-specific thing here; from the omim.txt.gz file, get the omim numbers
        #not unzipping the file
        print("INFO: Obtaining OMIM record identifiers")
        line_counter=0
        omimfile=('/').join((self.rawdir,self.files['all']['file']))
        print("FILE:",omimfile)
        #todo check to see if the file is there
        call(["uncompress", omimfile])
        omimfile = omimfile.replace('.Z','')
        with open(omimfile, "r") as f:
            for line in f:
                line=line.strip()

                if (line=="*FIELD* NO"):
                   line_counter += 1
                   #read the next line
                   number=f.readline().strip()
                   omimids.append(number)

        #recompress the file
        call(["compress",omimfile])
        print("INFO: Done.  I found",omimids.__len__(),"omim ids")
        return omimids

    def _process_all(self,limit,testMode):
        """
        This takes the list of omim identifiers from the omim.txt.Z file,
        and iteratively queries the omim api for the json-formatted data.
        This will create OMIM classes, with the label, definition, and some synonyms.
        If an entry is "removed", it is added as a deprecated class.
        If an entry is "moved", it is deprecated and consider annotations are added.

        Additionally, we extract:
        *phenotypicSeries ids as superclasses
        *equivalent ids for Orphanet and UMLS

        If set to testMode, it will write only those items in the test_ids to the testgraph.

        :param limit:
        :return:
        """

        omimids = []  #to store the set of omim identifiers
        omimids = self._get_omim_ids()

        omimparams = {
            'format' : 'json',
            'include' : 'all',
        }
        #you will need to add the API key into the conf.json file, like:
        # keys : { 'omim' : '<your api key here>' }
        omimparams.update({'apiKey' : config.get_config()['keys']['omim']})

        #http://api.omim.org/api/entry?mimNumber=100100&include=all

        if testMode:
            g = self.testgraph
        else:
            g = self.graph

        gu = GraphUtils(curie_map.get())

        it=0  #for counting

        #note that you can only do request batches of 20
        #see info about "Limits" at http://omim.org/help/api
        groupsize=20
        if not testMode and (limit is not None):
            #just in case the limit is larger than the number of records, max it out
            max = min((limit,omimids.__len__()))
        else:
            max=omimids.__len__()
        #max = 10 #for testing

        #TODO write the json to local files - make the assumption that downloads within 24 hrs are the same
        #now, loop through the omim numbers and pull the records as json docs
        while it < max:
            end=min((max,it+groupsize))
            #iterate through the omim ids list, and fetch from the OMIM api in batches of 20

            if testMode:
                intersect=list(set([str(i) for i in self.test_ids]) & set(omimids[it:end]))
                if (len(intersect) > 0):  #some of the test ids are in the omimids
                    print("found test ids:",intersect)
                    omimparams.update({'mimNumber' : (',').join(intersect)})
                else:
                    it+=groupsize
                    continue
            else:
                omimparams.update({'mimNumber' : (',').join(omimids[it:end])})

            p = urllib.parse.urlencode(omimparams)
            url = ('/').join((self.OMIM_API,'entry'))+'?%s' % p
            print ('fetching:',('/').join((self.OMIM_API,'entry'))+'?%s' % p)

            ### if you want to test a specific entry number, uncomment the following code block
            #if ('101600' in omimids[it:end]):  #104000
            #    print("FOUND IT in",omimids[it:end])
            #else:
            #   #testing very specific record
            #    it+=groupsize
            #    continue
            ### end code block for testing


            #print ('fetching:',(',').join(omimids[it:end]))
            #print('url:',url)
            d = urllib.request.urlopen(url)
            resp = d.read().decode()
            request_time = datetime.now()
            it+=groupsize

            myjson = json.loads(resp)
            entries = myjson['omim']['entryList']

            geno = Genotype(g)
            geno.addGenome('NCBITaxon:9606','Homo sapiens')


            for e in entries:

                #get the numbers, labels, and descriptions
                omimnum = e['entry']['mimNumber']
                titles = e['entry']['titles']
                label = titles['preferredTitle']

                other_labels = []
                if 'alternativeTitles' in titles:
                    other_labels += self._get_alt_labels(titles['alternativeTitles'])
                if 'includedTitles' in titles:
                    other_labels += self._get_alt_labels(titles['includedTitles'])

                #add synonyms of alternate labels
                #preferredTitle": "PFEIFFER SYNDROME",
                #"alternativeTitles": "ACROCEPHALOSYNDACTYLY, TYPE V; ACS5;;\nACS V;;\nNOACK SYNDROME",
                #"includedTitles": "CRANIOFACIAL-SKELETAL-DERMATOLOGIC DYSPLASIA, INCLUDED"

                #remove the abbreviation (comes after the ;) from the preferredTitle, and add it as a synonym
                abbrev = None
                if (len(re.split(';',label)) > 1):
                    abbrev = (re.split(';',label)[1].strip())
                newlabel = self._cleanup_label(label)

                description = self._get_description(e['entry'])
                omimid='OMIM:'+str(omimnum)

                if (e['entry']['status'] == 'removed'):
                    gu.addDeprecatedClass(g,omimid)
                else:
                    omimtype = self._get_omimtype(e['entry'])
                    #this uses our cleaned-up label
                    gu.addClassToGraph(g,omimid,newlabel,omimtype)

                    #add the original OMIM label as a synonym
                    gu.addSynonym(g,omimid,label)

                    #add the alternate labels and includes as synonyms
                    for l in other_labels:
                        gu.addSynonym(g,omimid,l)


                    #for OMIM, we're adding the description as a definition
                    gu.addDefinition(g,omimid,description)
                    if (abbrev is not None):
                        gu.addSynonym(g,omimid,abbrev)


                    #if this is a genetic locus (but not sequenced) then add the chrom loc info
                    if omimtype==Genotype.genoparts['biological_region']:
                        if 'geneMapExists' in e['entry'] and e['entry']['geneMapExists']:
                            genemap = e['entry']['geneMap']
                            if 'cytoLocation' in genemap:
                                cytoloc = genemap['cytoLocation']
                                #parse the cytoloc.  add this omim thing as a subsequence of the cytofeature
                                #18p11.3-p11.2
                                #for now, just take the first one
                                #FIXME add the other end of the range, but not sure how to do that
                                #not sure if saying subsequence of feature is the right relationship
                                cytoloc = cytoloc.split('-')[0]
                                f = Feature(omimid,None,None)
                                if 'chromosome' in genemap:
                                    chrom = makeChromID(str(genemap['chromosome']),'NCBITaxon:9606')
                                    geno.addChromosome(str(genemap['chromosome']),'NCBITaxon:9606','Homo sapiens')
                                    loc = makeChromID(cytoloc,'NCBITaxon:9606')
                                    geno.addChromosome(cytoloc,'NCBITaxon:9606','Homo sapiens')
                                    f.addSubsequenceOfFeature(g,loc)
                                    f.addFeatureToGraph(g)
                                pass


                    #check if moved, if so, make it deprecated and replaced/consider class to the other thing(s)
                    #some entries have been moved to multiple other entries and use the joining raw word "and"
                    #612479 is movedto:  "603075 and 603029"  OR
                    #others use a comma-delimited list, like:
                    #610402 is movedto: "609122,300870"
                    if (e['entry']['status'] == 'moved'):
                        if (re.search('and',str(e['entry']['movedTo']))):
                            #split the movedTo entry on 'and'
                            newids=re.split('and',str(e['entry']['movedTo']))
                        elif(len(str(e['entry']['movedTo']).split(',')) > 0):
                            #split on the comma
                            newids = str(e['entry']['movedTo']).split(',')
                        else:
                            #make a list of one
                            newids = [str(e['entry']['movedTo'])]
                        #cleanup whitespace and add OMIM prefix to numeric portion
                        fixedids = []
                        for i in newids:
                            fixedids.append('OMIM:'+i.strip())

                        gu.addDeprecatedClass(g,omimid,fixedids)

                    self._get_phenotypicseries_parents(e['entry'],g)
                    self._get_mappedids(e['entry'],g)

                    self._get_pubs(e['entry'],g)


                ###end iterating over batch of entries

            #can't have more than 4 req per sec,
            #so wait the remaining time, if necessary
            dt=datetime.now()-request_time
            rem=0.25-dt.total_seconds()
            if (rem > 0):
                print("INFO: waiting",str(rem),'s')
                time.sleep(rem/1000)

            gu.loadAllProperties(g)

        return

    def _process_morbidmap(self,limit,testMode):
        """
        This will process the morbidmap file to get the links between omim genes and diseases.
        Here, we create anonymous nodes for some variant loci that are variants of the gene that causes the disease.
        Triples created:
        <some_anonymous_variant_locus> is_sequence_variant_instance_of <omim_gene_id>
        <some_anonymous_variant_locus> has_phenotype <omim_disease_id>
        <assoc> hasSubject <some_anonymous_variant_locus>
        <assoc> hasObject <omim_disease_id>
        <assoc> hasPredicate <has_phenotype>
        <assoc> DC:evidence <eco_id>
        :param limit:
        :return:
        """
        if testMode:
            g = self.testgraph
        else:
            g = self.graph
        line_counter = 0
        geno = Genotype(g)
        gu = GraphUtils(curie_map.get())
        with open(('/').join((self.rawdir,self.files['morbidmap']['file']))) as f:
            for line in f:
                line = line.strip()
                line_counter += 1
                (disorder,gene_symbols,gene_num,loc) = line.split('|')

                #disorder = disorder label , number (mapping key)
                #3-M syndrome 1, 273750 (3)|CUL7, 3M1|609577|6p21.1

                #but note that for those diseases where they are genomic loci (not genes though),
                #the omim id is only listed as the gene
                #Alopecia areata 1 (2)|AA1|104000|18p11.3-p11.2
                disorder_match = re.match('(.*), (\d+) \((\d+)\)',disorder)

                if (disorder_match is not None):
                    disorder_parts = disorder_match.groups()
                    if (len(disorder_parts) == 3):
                        (disorder_label,disorder_num,phene_key) = disorder_parts
                    else:
                        print("WARN: I couldn't parse disorder string:",disorder)
                        continue

                    if testMode and (int(disorder_num) not in self.test_ids or int(gene_num) not in self.test_ids):
                            continue
                    gene_symbols = gene_symbols.split(', ')
                    gene_id = (':').join(('OMIM',gene_num))
                    disorder_id = (':').join(('OMIM',disorder_num))

                    evidence = self._map_phene_mapping_code_to_eco(phene_key)


                    assoc_id = self.make_id((disorder_id+gene_id+phene_key))

                    #we actually want the association between the gene and the disease to be via an alternate locus
                    #not the "wildtype" gene itself.
                    #so we make an anonymous alternate locus, and put that in the association.
                    alt_locus = '_'+gene_num+'-'+disorder_num+'VL'
                    alt_label = gene_symbols[0].strip()
                    if alt_label is not None and alt_label != '':
                        alt_label = 'some variant of '+alt_label.strip()+' that causes '+disorder_label
                    else:
                        alt_label = None
                    gu.addIndividualToGraph(g,alt_locus,alt_label,geno.genoparts['variant_locus'])
                    geno.addAlleleOfGene(alt_locus,gene_id)

                    assoc = G2PAssoc(assoc_id,alt_locus,disorder_id,None,evidence)
                    assoc.loadAllProperties(g)
                    assoc.addAssociationToGraph(g)

                if not testMode and (limit is not None and line_counter > limit):
                    break

            gu.loadProperties(g,geno.object_properties,gu.OBJPROP)

        return

    def _get_description(self,entry):
        """
        Get the description of the omim entity from the textSection called 'description'.
        Note that some of these descriptions have linebreaks.  If printed in turtle syntax,
        they will appear to be triple-quoted.
        :param entry:
        :return:
        """
        d = None
        if entry is not None:
            #print(entry)
            if 'textSectionList' in entry:
                textSectionList = entry['textSectionList']
                for ts in textSectionList:
                    if ts['textSection']['textSectionName'] == 'description':
                        d = ts['textSection']['textSectionContent']
                        #there are internal references to OMIM identifiers in the description, I am
                        #formatting them in our style.
                        d = re.sub('{(\\d+)}','OMIM:\\1',d)

                        #TODO reformat the citations in the description with PMIDs
                        break


        return d

    def _map_phene_mapping_code_to_eco(self,code):
        #phenotype mapping code
        #1 - the disorder is placed on the map based on its association with a gene, but the underlying defect is not known.
        #2 - the disorder has been placed on the map by linkage; no mutation has been found.
        #3 - the molecular basis for the disorder is known; a mutation has been found in the gene.
        #4 - a contiguous gene deletion or duplication syndrome, multiple genes are deleted or duplicated causing the phenotype.
        eco_code = 'ECO:0000000' #generic evidence
        phene_code_to_eco = {
            '1' : 'ECO:0000306', #inference from background scientific knowledge used in manual assertion
            '2' : 'ECO:0000177', #genomic context evidence
            '3' : 'ECO:0000220', #sequencing assay evidence
            '4' : 'ECO:0000220'  #sequencing assay evidence
        }

        if (str(code) in phene_code_to_eco):
            eco_code = phene_code_to_eco.get(code)
        else:
            print("ERROR: unmapped phene code",code)

        return eco_code

    def _cleanup_label(self,label):
        """
        Reformat the ALL CAPS OMIM labels to something more pleasant to read.  This will:
        1.  remove the abbreviation suffixes
        2.  convert the roman numerals to integer numbers
        3.  make the text title case, except for conjunctions/prepositions/articles
        :param label:
        :return:
        """
        #remove the abbreviation

        conjunctions = ['and','but','yet','for','nor','so']
        little_preps = ['at', 'by', 'in', 'of', 'on', 'to', 'up', 'as', 'it', 'or']
        articles = ['a', 'an', 'the']

        l = re.split(';',label)[0]

        #convert roman numbers into actual numbers
        fixedwords = []
        i=0
        for w in l.split():
            i += 1
            #convert the roman numerals to numbers, but assume that the first word is not
            #a roman numeral (this permits things like "X inactivation"
            if ((i>1) and (re.match(romanNumeralPattern,w))):
                n = fromRoman(w)
                #make the assumption that the number of syndromes are <100
                #this allows me to retain "SYNDROME C" and not convert it to "SYNDROME 100"
                if (0 < n < 100):
                    #get the non-roman suffix, if present.  for example, IIIB or IVA
                    suffix = w.replace(toRoman(n),'',1)
                    fixed = ('').join((str(n),suffix))
                    w = fixed

            #capitalize first letter
            w = w.title()

            #replace interior conjunctions, prepositions, and articles with lowercase
            if ((w.lower() in (conjunctions+little_preps+articles)) and (i != 1)):
                w = w.lower()

            fixedwords.append(w)

        l=(' ').join(fixedwords)
        #print (label,'-->',l)
        return l

    def _process_phenotypicseries(self,limit,testMode):
        """
        Creates classes from the OMIM phenotypic series list.  These are grouping classes
        to hook the more granular OMIM diseases.
        :param limit:
        :return:
        """
        if testMode:
            g = self.testgraph
        else:
            g = self.graph
        print("INFO: getting phenotypic series titles")
        gu = GraphUtils(curie_map.get())
        line_counter = 0
        start=False
        with open(('/').join((self.rawdir,self.files['phenotypicSeries']['file']))) as f:
            for line in f:
                #there's several lines of header in the file, so need to skip several lines:
                if not start:
                    if re.match('Phenotypic Series',line):
                        start=True
                    continue
                if re.match('\w*$',line):
                    #skip blank lines
                    continue
                line = line.strip()
                line_counter += 1
                (ps_label,ps_num) = line.split('\t')
                omim_id = 'OMIM:'+ps_num
                gu.addClassToGraph(g,omim_id,ps_label)

        return

    def _get_phenotypicseries_parents(self,entry,g):
        """
        Extract the phenotypic series parent relationship out of the entry
        :param entry:
        :return:
        """
        gu = GraphUtils(curie_map.get())
        omimid = 'OMIM:'+str(entry['mimNumber'])
        #the phenotypic series mappings
        serieslist = []
        if 'phenotypicSeriesExists' in entry :
            if entry['phenotypicSeriesExists'] == True:
                if 'phenotypeMapList' in entry:
                    phenolist = entry['phenotypeMapList']
                    for p in phenolist:
                        serieslist.append(p['phenotypeMap']['phenotypicSeriesNumber'])
                if 'geneMap' in entry and 'phenotypeMapList' in entry['geneMap']:
                    phenolist = entry['geneMap']['phenotypeMapList']
                    for p in phenolist:
                        if 'phenotypicSeriesNumber' in p['phenotypeMap']:
                            serieslist.append(p['phenotypeMap']['phenotypicSeriesNumber'])
        #add this entry as a subclass of the series entry
        for ser in serieslist:
            series_id = 'OMIM:'+ser
            gu.addClassToGraph(g,series_id,None)
            gu.addSubclass(g,series_id,omimid)

        return

    def _get_mappedids(self,entry,g):
        """
        Extract the Orphanet and UMLS ids as equivalences from the entry
        :param entry:
        :return:
        """
        #umlsIDs
        gu = GraphUtils(curie_map.get())
        omimid = 'OMIM:'+str(entry['mimNumber'])
        orpha_mappings = []
        if 'externalLinks' in entry:
            links = entry['externalLinks']
            if 'orphanetDiseases' in links:
                #triple semi-colon delimited list of double semi-colon delimited orphanet ID/disease pairs
                #2970;;566;;Prune belly syndrome
                items  = links['orphanetDiseases'].split(';;;')
                for i in items:
                    (orpha_num,internal_num,orpha_label) = i.split(';;')
                    orpha_id = 'Orphanet:'+orpha_num.strip()
                    orpha_mappings.append(orpha_id)
                    gu.addClassToGraph(g,orpha_id,orpha_label.strip())
                    gu.addXref(g,omimid,orpha_id)

            if 'umlsIDs' in links:
                umls_mappings = links['umlsIDs'].split(',')
                for i in umls_mappings:
                    umls_id = 'UMLS:'+i
                    gu.addClassToGraph(g,umls_id,None)
                    gu.addXref(g,omimid,umls_id)

            if ((self._get_omimtype(entry) == Genotype.genoparts['gene'])
                and ('geneIDs' in links)):
                entrez_mappings = links['geneIDs']
                for i in entrez_mappings.split(','):
                    gu.addEquivalentClass(g,omimid,'NCBIGene:'+str(i))


        return

    def _get_alt_labels(self,titles):
        """
        From a string of delimited titles, make an array.  This assumes that the titles are double-semicolon (';;')
        delimited.  This will additionally pass each through the _cleanup_label method to convert the
        screaming ALL CAPS to something more pleasant to read.
        :param titles:
        :return: an array of cleaned-up labels
        """

        labels = []
        #"alternativeTitles": "ACROCEPHALOSYNDACTYLY, TYPE V; ACS5;;\nACS V;;\nNOACK SYNDROME",
        #"includedTitles": "CRANIOFACIAL-SKELETAL-DERMATOLOGIC DYSPLASIA, INCLUDED"

        for t in titles.split(';;'):
            #remove ', included', if present
            l = re.sub(',\s*INCLUDED','',t.strip(),re.IGNORECASE)
            l = self._cleanup_label(l)
            labels.append(l)

        #print('labels:',labels)
        return labels

    def _get_pubs(self,entry,g):
        """
        Extract mentioned publications from the reference list
        :param entry:
        :return:
        """

        gu = GraphUtils(curie_map.get())
        if 'referenceList' in entry:
            for r in entry['referenceList']:
                if 'reference' in r:
                    omimid = 'OMIM:'+str(r['reference']['mimNumber'])
                    if 'pubmedID' in r['reference']:
                        pmid = 'PMID:'+str(r['reference']['pubmedID'])
                        gu.addTriple(g,omimid,gu.object_properties['mentions'],pmid)
                    elif 'articleUrl' in r['reference']:
                        print('INFO: No PMID for reference',str(r['reference']['referenceNumber']),'in',omimid)
                        articleurl = r['reference']['articleUrl']
                        #gu.addTriple(g,omimid,gu.object_properties['mentions'],articleurl)
                else:
                    print('INFO:keys for item in reference list:',r.keys())



        return

    def _get_omimtype(self,entry):
        """
        Here, we look at the omim 'prefix' to help to type the entry.  For now, we only classify omim entries
        as genes; the rest we leave alone.
        :param entry:
        :return:
        """
        # An asterisk (*) before an entry number indicates a gene.
        # A number symbol (#) before an entry number indicates that it is a descriptive entry,
        # usually of a phenotype, and does not represent a unique locus.
        # The reason for the use of the number symbol is given in the first paragraph of the entry.
        # Discussion of any gene(s) related to the phenotype resides in another entry(ies) as described in the first paragraph.
        #
        # A plus sign (+) before an entry number indicates that the entry contains the description of
        # a gene of known sequence and a phenotype.
        #
        # A percent sign (%) before an entry number indicates that the entry describes a confirmed mendelian
        # phenotype or phenotypic locus for which the underlying molecular basis is not known.
        #
        # No symbol before an entry number generally indicates a description of a phenotype for which the
        # mendelian basis, although suspected, has not been clearly established or that the separateness of this
        # phenotype from that in another entry is unclear.
        #
        # A caret (^) before an entry number means the entry no longer exists because it was removed from the
        # database or moved to another entry as indicated.
        prefix = None
        type_id = None
        if 'prefix' in entry:
            prefix = entry['prefix']

        if prefix == '*':
            #gene, may not have a known sequence or a phenotype
            #examples: 102560,102480,100678,102750
            type_id = Genotype.genoparts['gene']  #doublecheck this
        elif prefix == '#' :
            #phenotype/disease -- indicate that here?
            #examples: 104200,105400,114480,115300,121900
            pass
        elif prefix == '+' :
            #gene of known sequence and has a phenotype
            #examples: 107670,110600,126453
            type_id = Genotype.genoparts['gene']  #doublecheck this
            pass
        elif prefix == '%' :
            #this is a disease (with a known locus).
            #examples include:  102150,104000,107200,100070
            type_id = Genotype.genoparts['biological_region']
            pass
        elif prefix == '' :
            #this is probably just a phenotype
            pass


        return type_id
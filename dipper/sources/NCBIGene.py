import os
from stat import *
import re
from datetime import datetime
import gzip
import os.path
import unicodedata

from dipper.sources.Source import Source
from dipper.models.Dataset import Dataset
from dipper.models.Assoc import Assoc
from dipper.utils.CurieUtil import CurieUtil
from dipper.utils.GraphUtils import GraphUtils
from dipper.curie import curie_map
from dipper.models.GenomicFeature import Feature,makeChromID


class NCBIGene(Source):
    """

    Parses the gene_info (gene names, symbols, ids, equivalent ids), gene history (alt ids), and
        publications about a gene, and
    """

    files = {
        'gene_info' : {
            'file' : 'gene_info.gz',
            'url' : 'http://ftp.ncbi.nih.gov/gene/DATA/gene_info.gz'
        },
        'gene_history' : {
            'file': 'gene_history.gz',
            'url' : 'http://ftp.ncbi.nih.gov/gene/DATA/gene_history.gz'
        },
        'gene2pubmed' : {
            'file': 'gene2pubmed.gz',
            'url' : 'http://ftp.ncbi.nih.gov/gene/DATA/gene2pubmed.gz'
        },
    }


    relationships = {
        'gene_product_of' : 'RO:0002204',
        'has_gene_product' : 'RO:0002205',
        'is_about' : 'IAO:00000136'
    }

    testmode = False

    def __init__(self):
        Source.__init__(self, 'ncbigene')

        self.load_bindings()

        self.dataset = Dataset('ncbigene', 'National Center for Biotechnology Information', 'http://ncbi.nih.nlm.gov/gene')
        #data-source specific warnings (will be removed when issues are cleared)
        #print()

        self.filters = {
            'taxids' : [9606,10090],
            'geneids' : [17151,100008564,17005,11834,14169]
        }

        #this filter will be applied to all parsing/outputing...
        #set to None if you don't want to apply a filter
        self.filter = 'taxids'

        if self.testmode:
            self.filter = 'geneids'

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

        self._get_gene_info(limit)
        self._get_gene_history(limit)
        self._get_gene2pubmed(limit)

        self.load_core_bindings()
        self.load_bindings()

        print("Done parsing files.")

        return

    def _get_gene_info(self,limit):
        '''
        Currently loops through the gene_info file and creates the genes as classes, typed with SO.  It will add their
        label, any alternate labels as synonyms, alternate ids as equivlaent classes.  HPRDs get added as
        protein products.  The chromosome and chr band get added as blank node regions, and the gene is faldo:located
        on the chr band.
        :param limit:
        :return:
        '''
        gu = GraphUtils(curie_map.get())
        cu = CurieUtil(curie_map.get())

        #not unzipping the file
        print("INFO: Processing Gene records")
        line_counter=0
        myfile=('/').join((self.rawdir,self.files['gene_info']['file']))
        print("FILE:",myfile)
        with gzip.open(myfile, 'rb') as f:
            for line in f:
                #skip comments
                line=line.decode().strip()
                if (re.match('^#',line)):
                    continue
                (tax_num,gene_num,symbol,locustag,
                 synonyms,xrefs,chr,map_loc,desc,
                 gtype,authority_symbol,name,
                 nomenclature_status,other_designations,modification_date) = line.split('\t')

                ##### set filter=None in init if you don't want to have a filter
                if self.filter is not None:
                    if ((self.filter == 'taxids' and (int(tax_num) not in self.filters[self.filter])) or
                        (self.filter == 'geneids' and (int(gene_num) not in self.filters[self.filter]))):
                        continue
                ##### end filter


                line_counter += 1

                gene_id = (':').join(('NCBIGene',gene_num))
                tax_id = (':').join(('NCBITaxon',tax_num))
                gene_type_id = self._map_type_of_gene(gtype)

                n = gu.getNode(gene_id)

                if (symbol == 'NEWENTRY'):
                    label = None
                else:
                    label = symbol

                #TODO might have to figure out if things aren't genes, and make them individuals
                gu.addClassToGraph(self.graph,gene_id,label,gene_type_id,desc)

                #todo use feature for refactor
                #we have to do special things here for genes, because they're classes not individuals
                f = Feature(gene_id,label,gene_type_id,desc)

                if (name != '-'):
                    gu.addSynonym(self.graph,gene_id,name)
                if (synonyms.strip() != '-'):
                    for s in synonyms.split('|'):
                        gu.addSynonym(self.graph,gene_id,s.strip(),Assoc.relationships['hasRelatedSynonym'])
                if (other_designations.strip() != '-'):
                    for s in other_designations.split('|'):
                        gu.addSynonym(self.graph,gene_id,s.strip(),Assoc.relationships['hasRelatedSynonym'])
                f.addTaxonToFeature(self.graph,tax_id)

                #deal with the xrefs
                #MIM:614444|HGNC:HGNC:16851|Ensembl:ENSG00000136828|HPRD:11479|Vega:OTTHUMG00000020696
                if (xrefs.strip() != '-'):
                    for r in xrefs.strip().split('|'):
                        fixedr = self._cleanup_id(r)
                        if ((fixedr is not None) and (fixedr.strip() != '')):
                            if (re.match('HPRD',fixedr)):
                                #proteins are not == genes.
                                self.graph.add((n,gu.getNode(self.relationships['has_gene_product']),gu.getNode(fixedr)))
                            else:
                                if (fixedr.split(':')[0] not in ['Vega','IMGT/GENE-DB']):  #skip these for now
                                    gu.addEquivalentClass(self.graph,gene_id,fixedr)

                if (str(chr) != '-'):
                    if (re.search('\|',str(chr))):
                        #this means that there's uncertainty in the mapping.  skip it
                        #TODO we'll need to figure out how to deal with >1 loc mapping
                        print(gene_id,'is non-uniquely mapped to',str(chr),'.  Skipping for now.')
                        continue
                    #if (not re.match('(\d+|(MT)|[XY]|(Un)$',str(chr).strip())):
                    #    print('odd chr=',str(chr))

                    mychrom = makeChromID(str(chr),tax_num)
                    chrom = Feature(mychrom,str(chr),Feature.types['chromosome'])
                    chrom.addFeatureToGraph(self.graph)
                    if (map_loc != '-'):
                        #this matches the regular kind of chrs, so make that kind of band
                        #not sure why this matches? chrX|Y or 10090chr12|Un"
                        #TODO we probably need a different regex per organism
                        if re.match('[0-9A-Z]+[pq](\d+)?(\.\d+)?$',map_loc):
                            #the maploc_id already has the numeric chromosome in it, strip it first
                            bid = re.sub('^'+str(chr),'',map_loc)
                            maploc_id = mychrom+bid
                            #print(map_loc,'-->',bid,'-->',maploc_id)
                            band = Feature(maploc_id,map_loc,Feature.types['chromosome_part'])  #FIXME
                            band.addFeatureToGraph(self.graph)
                            f.addSubsequenceOfFeature(self.graph,maploc_id)  #add band as the containing feature
                        else:
                            #TODO handle these cases
                            #examples are: 15q11-q22, Xp21.2-p11.23, 15q22-qter, 10q11.1-q24,
                            ## 12p13.3-p13.2|12p13-p12, 1p13.3|1p21.3-p13.1,  12cen-q21, 22q13.3|22q13.3
                            print('not regular band pattern for',gene_id,':',map_loc)

                if (limit is not None and line_counter > limit):
                    break

        return


    def _get_gene_history(self,limit):
        '''
        Loops through the gene_history file and adds the old gene ids as deprecated classes, where the new
        gene id is the replacement for it.  The old gene symbol is added as a synonym to the gene.
        :param limit:
        :return:
        '''
        gu = GraphUtils(curie_map.get())

        print("INFO: Processing Gene records")
        line_counter=0
        myfile=('/').join((self.rawdir,self.files['gene_history']['file']))
        print("FILE:",myfile)
        with gzip.open(myfile, 'rb') as f:
            for line in f:
                #skip comments
                line=line.decode().strip()
                if (re.match('^#',line)):
                    continue
                (tax_num,gene_num,discontinued_num,discontinued_symbol,discontinued_date) = line.split('\t')

                ##### set filter=None in init if you don't want to have a filter
                if self.filter is not None:
                    if ((self.filter == 'taxids' and (int(tax_num) not in self.filters[self.filter])) or
                        (self.filter == 'geneids' and (int(gene_num) not in self.filters[self.filter]))):
                        continue
                ##### end filter

                if (gene_num == '-' or discontinued_num =='-'):
                    continue
                line_counter += 1
                gene_id = (':').join(('NCBIGene',gene_num))
                discontinued_gene_id = (':').join(('NCBIGene',discontinued_num))
                tax_id = (':').join(('NCBITaxon',tax_num))

                #add the two genes
                gu.addClassToGraph(self.graph,gene_id,None)
                gu.addClassToGraph(self.graph,discontinued_gene_id,discontinued_symbol)

                #add the new gene id to replace the old gene id
                gu.addDeprecatedClass(self.graph,discontinued_gene_id,[gene_id])

                #also add the old symbol as a synonym of the new gene
                gu.addSynonym(self.graph,gene_id,discontinued_symbol)

                if (limit is not None and line_counter > limit):
                    break

        return

    def _get_gene2pubmed(self,limit):
        '''
        Loops through the gene2pubmed file and adds a simple triple to say that a given publication
        is_about a gene.  Publications are added as NamedIndividuals.
        :param limit:
        :return:
        '''

        gu = GraphUtils(curie_map.get())
        is_about = gu.getNode(self.relationships['is_about'])

        print("INFO: Processing Gene records")
        line_counter=0
        myfile=('/').join((self.rawdir,self.files['gene2pubmed']['file']))
        print("FILE:",myfile)
        with gzip.open(myfile, 'rb') as f:
            for line in f:
                #skip comments
                line=line.decode().strip()
                if (re.match('^#',line)):
                    continue
                (tax_num,gene_num,pubmed_num) = line.split('\t')

                ##### set filter=None in init if you don't want to have a filter
                if self.filter is not None:
                    if ((self.filter == 'taxids' and (int(tax_num) not in self.filters[self.filter])) or
                        (self.filter == 'geneids' and (int(gene_num) not in self.filters[self.filter]))):
                        continue
                ##### end filter

                if (gene_num == '-' or pubmed_num =='-'):
                    continue
                line_counter += 1
                gene_id = (':').join(('NCBIGene',gene_num))
                pubmed_id = (':').join(('PMID',pubmed_num))

                #add the gene, in case it hasn't before
                gu.addClassToGraph(self.graph,gene_id,None)
                #add the publication as a NamedIndividual
                gu.addIndividualToGraph(self.graph,pubmed_id,None,None)  #add type publication
                self.graph.add((gu.getNode(pubmed_id),is_about,gu.getNode(gene_id)))

                if (limit is not None and line_counter > limit):
                    break

        return

    def _map_type_of_gene(self,type):
        so_id = 'SO:0000704'
        type_to_so_map = {
            'ncRNA': 'SO:0001263',
            'other': 'SO:0000704',
            'protein-coding': 'SO:0001217',
            'pseudo': 'SO:0000336',
            'rRNA': 'SO:0001637',
            'snRNA': 'SO:0001268',
            'snoRNA': 'SO:0001267',
            'tRNA': 'SO:0001272',
            'unknown': 'SO:0000704',
            'scRNA' : 'SO:0000013',
            'miscRNA' : 'SO:0000233', #mature transcript - there is no good mapping
            'chromosome' : 'SO:0000340',
            'chromosome_arm' : 'SO:0000105',
            'chromosome_band' : 'SO:0000341',
            'chromosome_part' : 'SO:0000830'
        }

        if (type in type_to_so_map):
            so_id = type_to_so_map.get(type)
        else:
            print("WARN: unmapped code",type,". Defaulting to 'SO:0000704'.")

        return so_id


        return so_id

    def _cleanup_id(self,i):
        cleanid = i
        #MIM:123456 --> #OMIM:123456
        cleanid = re.sub('^MIM','OMIM',cleanid)

        #HGNC:HGNC --> HGNC
        cleanid = re.sub('^HGNC:HGNC','HGNC',cleanid)

        #Ensembl --> ENSEMBL
        cleanid = re.sub('^Ensembl','ENSEMBL',cleanid)

        #MGI:MGI --> MGI
        cleanid = re.sub('^MGI:MGI','MGI',cleanid)

        return cleanid


    def remove_control_characters(self,s):
        return "".join(ch for ch in s if unicodedata.category(ch)[0]!="C")
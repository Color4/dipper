import os
from stat import *
import urllib
from urllib import request
import re
import time
from datetime import datetime
import gzip,os.path
import json
from rdflib import Graph, Literal, URIRef, Namespace, BNode
from rdflib.namespace import RDF, RDFS, OWL, DC,XSD
from sources.Source import Source

from models.D2PAssoc import D2PAssoc
from models.DispositionAssoc import DispositionAssoc
from models.Dataset import Dataset
from models.Assoc import Assoc
from utils.CurieUtil import CurieUtil
from utils.GraphUtils import GraphUtils
import config

class NCBIGene(Source):
    '''

    '''

    files = {
        'gene_info' : {
            'file' : 'gene_info.gz',
            'url' : 'ftp://ftp.ncbi.nih.gov/gene/DATA/gene_info.gz'
        },
        #'gene_history' : {
        #    'file': 'gene_history.gz',
        #    'url' : 'ftp://ftp.ncbi.nih.gov/gene/DATA/gene_history.gz'
        #},
        #'gene2pubmed' : {
        #    'file': 'gene2pubmed.gz',
        #    'url' : 'ftp://ftp.ncbi.nih.gov/gene/DATA/gene2pubmed.gz'
        #},
    }

    prefixes = {
        'NCBIGene' : 'http://ncbi.nlm.nih.gov/gene/',
        'faldo' : 'http://biohackathon.org/resource/faldo#',
        'NCBITaxon' : 'http://ncbi.nlm.nih.gov/taxonomy/',
        'SO' : 'http://purl.obolibrary.org/obo/SO_',
        'OMIM' : 'http://omim.org/entry/',
        'HGNC' : 'http://www.genenames.org/cgi-bin/gene_symbol_report?hgnc_id=HGNC:',
        'HPRD' : 'http://www.hprd.org/protein/',
        'ENSEMBL' : 'http://identifiers.org/ENSEMBL:',
        'miRBase' : 'http://www.mirbase.org/cgi-bin/mirna_entry.pl?acc=',
        'MGI': 'http://www.informatics.jax.org/accession/MGI:',  #All MGI ids are genes in this case
    }

    curie_map = {}

    relationships = {
        'gene_product_of' : 'RO:0002204',
        'has_gene_product' : 'RO:0002205'
    }


    def __init__(self):
        Source.__init__(self, 'ncbigene')
        self.curie_map.update(Assoc.curie_map)
        self.curie_map.update(D2PAssoc.curie_map)
        self.curie_map.update(DispositionAssoc.curie_map)
        self.curie_map.update(self.prefixes)

        self.load_bindings()

        self.dataset = Dataset('ncbigene', 'National Center for Biotechnology Information', 'http://ncbi.nih.nlm.gov/gene')
        #data-source specific warnings (will be removed when issues are cleared)
        #print()

        return

    def fetch(self):
        #this is fetching the standard files, not from the API/REST service
        for f in self.files.keys():
            file = self.files.get(f)
            self.fetch_from_url(file['url'],('/').join((self.rawdir,file['file'])))
            self.dataset.setFileAccessUrl(file['url'])
            st = os.stat(('/').join((self.rawdir,file['file'])))

        filedate=datetime.utcfromtimestamp(st[ST_CTIME]).strftime("%Y-%m-%d")

        self.dataset.setVersion(filedate)

        return


    def scrub(self):
        '''
        Perform various data-scrubbing on the raw data files prior to parsing.
        For this resource, this currently includes: (Nothing)
        :return: None
        '''
        return

    def load_bindings(self):
        self.load_core_bindings()
        for k in self.curie_map.keys():
            v=self.curie_map[k]
            self.graph.bind(k, Namespace(v))
        return

    def parse(self, limit=None):
        if (limit is not None):
            print("Only parsing first", limit, "rows")

        print("Parsing files...")


        g = self.graph

        gu = GraphUtils(self.curie_map)
        cu = CurieUtil(self.curie_map)

        self._get_gene_info(limit)

        ##### Write it out #####
        filewriter = open(self.outfile, 'w')
        self.load_core_bindings()
        self.load_bindings()

        print("Finished parsing files. Writing turtle to",self.outfile)
        print(g.serialize(format="turtle").decode(),file=filewriter)
        filewriter.close()


        return

    def _get_gene_info(self,limit):
        gu = GraphUtils(self.curie_map)
        cu = CurieUtil(self.curie_map)

        exact=URIRef(cu.get_uri(Assoc.relationships['hasExactSynonym']))
        related=URIRef(cu.get_uri(Assoc.relationships['hasRelatedSynonym']))
        intaxon=URIRef(cu.get_uri(Assoc.relationships['in_taxon']))
        begin = URIRef(cu.get_uri('faldo:begin'))
        end = URIRef(cu.get_uri('faldo:end'))
        region = URIRef(cu.get_uri('faldo:Region'))
        loc = URIRef(cu.get_uri('faldo:location'))
        bagofregions = URIRef(cu.get_uri('faldo:BagOfRegions'))

        #an omim-specific thing here; from the omim.txt.gz file, get the omim numbers
        #not unzipping the file
        print("INFO: Processing Gene records")
        line_counter=0
        myfile=('/').join((self.rawdir,self.files['gene_info']['file']))
        print("FILE:",myfile)
        with gzip.open(myfile, 'rb') as f:
            for line in f:
                #skip comments
                line=line.decode().strip()
                line_counter += 1
                if (re.match('^#',line)):
                    continue
                (tax_num,gene_num,symbol,locustag,
                 synonyms,xrefs,chr,map_loc,desc,
                 gtype,authority_symbol,name,
                 nomenclature_status,other_designations,modification_date) = line.split('\t')

                ##### uncomment the next few lines to apply a taxon filter
                taxids = [9606,10090]
                if (int(tax_num) not in taxids):
                #if (gene_num != '1'):  #for testing, apply a specific gene filter
                    continue
                ##### end taxon filter

                gene_id = (':').join(('NCBIGene',gene_num))
                tax_id = (':').join(('NCBITaxon',tax_num))
                gene_type_id = self._map_type_of_gene(gtype)

                n = URIRef(cu.get_uri(gene_id))
                t = URIRef(cu.get_uri(gene_type_id))
                if (symbol == 'NEWENTRY'):
                    label = None
                else:
                    label = symbol
                gu.addClassToGraph(self.graph,gene_id,label,None,desc)

                #we are making genes classes, not instances.  so add it as a subclass here
                self.graph.add((n,Assoc.OWLSUBCLASS,t))
                if (name != '-'):
                    self.graph.add((n,exact,Literal(name)))
                if (synonyms.strip() != '-'):
                    for s in synonyms.split('|'):
                        self.graph.add((n,related,Literal(s.strip())))
                if (other_designations.strip() != '-'):
                    for s in other_designations.split('|'):
                        self.graph.add((n,related,Literal(s.strip())))
                self.graph.add((n,intaxon,URIRef(cu.get_uri(tax_id))))

                #deal with the xrefs
                #MIM:614444|HGNC:HGNC:16851|Ensembl:ENSG00000136828|HPRD:11479|Vega:OTTHUMG00000020696
                if (xrefs.strip() != '-'):
                    for r in xrefs.strip().split('|'):
                        fixedr = self._cleanup_id(r)
                        if ((fixedr is not None) and (fixedr.strip() != '')):
                            if (re.match('HPRD',fixedr)):
                                self.graph.add((n,URIRef(cu.get_uri(self.relationships['has_gene_product'])),URIRef(cu.get_uri(fixedr))))
                            else:
                                if (fixedr.split(':')[0] not in ['Vega','IMGT/GENE-DB']):  #skip these for now
                                    gu.addEquivalentClass(self.graph,gene_id,fixedr)
                        #todo, make sure to not make protein ids equivalent!  for example, HPRD==protein id
                        #use gene_product_of RO:0002204

                #we don't get actual coords, just chr and band
                #make them blank nodes for now
                #TODO what kind of URI would i make for chromosomes???
                if (str(chr) != '-'):
                    mychrom=('').join((tax_num,'chr',str(chr)))
                    chrom = BNode(mychrom)
                    self.graph.add((chrom,RDF['type'],bagofregions))
                    self.graph.add((chrom,loc,Literal(chr)))  #should probably be a reference?
                    if (map_loc != '-'):
                        band = BNode(map_loc)
                        self.graph.add((n,loc,band))
                        self.graph.add((band,RDF['type'],region))
                        self.graph.add((band,loc,chrom))
                        self.graph.add((n,loc,Literal(map_loc)))

                #deal with coordinate information:
                #make blank nodes for the regions, and positions
                #generegion = BNode((':').join((chr,map_loc)))
                #self.graph.add((n,loc,generegion))
                #self.graph.add((generegion,RDF['type'],region))
                #self.graph.add((generegion,begin,Literal(map_loc)))
                #self.graph.add((generegion,end,Literal(map_loc)))

                #todo add reference and strand info

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
            'scRNA' : 'SO:0000013'
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
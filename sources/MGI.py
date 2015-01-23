import csv
import os
from datetime import datetime
from stat import *
import re
import psycopg2


from rdflib import Literal
from rdflib.namespace import RDFS, OWL, RDF, DC
from rdflib import Namespace, URIRef, BNode

from utils import pysed
from sources.Source import Source
from models.Assoc import Assoc
from models.Genotype import Genotype
from models.Dataset import Dataset
from models.G2PAssoc import G2PAssoc
from utils.CurieUtil import CurieUtil
import config
import curie_map
from utils.GraphUtils import GraphUtils


class MGI(Source):
    '''
    Be sure to have pg user/password connection details in your conf.json file, like:
      dbauth : {
        'mgi' : {'user' : '<username>', 'password' : '<password>'}
      }
    '''
# tables in existing interop
# mgi_organism_acc_view mgi_organism_view gxd_genotype_view gxd_allelepair_view mrk_marker_view
# mgi_reference_allele_view bib_acc_view voc_annot_view gxd_genotype_summary_view voc_evidence_view
# all_allele_cellline_view voc_term_view all_allele_view all_allele_mutation_view prb_strain_view
# all_summary_view mrk_summary_view mgi_note_vocevidence_view acc_logicaldb_view mgi_note_strain_view
# prb_strain_acc_view prb_strain_summary_view prb_strain_marker_view
    tables = [
        'mgi_dbinfo',
        'gxd_genotype_view',
        'gxd_genotype_summary_view',
        'gxd_allelepair_view',
        'all_summary_view',
        'all_allele_view',
        'all_allele_mutation_view',
        'mrk_marker_view'
    ]


    relationship = {
        'is_mutant_of' : 'GENO:0000440',
        'derives_from' : 'RO:0001000',
        'has_alternate_part' : 'GENO:0000382',
        'has_reference_part' : 'GENO:0000385',
        'in_taxon' : 'RO:0000216',
        'has_zygosity' : 'GENO:0000608',   #what exactly "has zygosity"?  is it the allele?  genotype?
        'is_sequence_variant_instance_of' : 'GENO:0000408',
        'hasExactSynonym' : 'OIO:hasExactSynonym',
        'has_disposition' : 'GENO:0000208'
    }

    terms = {
        'variant_locus' : 'GENO:0000483',
        'reference_locus' : 'GENO:0000036',
        'sequence_alteration' : 'SO:0001059',
        'variant_single_locus_complement' : 'GENO:0000030',
        'allele' : 'GENO:0000008',
        'intrinsic_genotype' : 'GENO:0000000'
    }

    def __init__(self):
        Source.__init__(self, 'mgi')
        self.namespaces.update(curie_map.get())
        #assemble all the curie mappings from the imported models
        #self.namespaces.update(Assoc.curie_map)
        #self.namespaces.update(Genotype.curie_map)
        #self.namespaces.update(G2PAssoc.curie_map)

        #update the dataset object with details about this resource
        self.dataset = Dataset('mgi', 'MGI', 'http://www.informatics.jax.org/')

        #check if config exists; if it doesn't, error out and let user know
        if (not (('dbauth' in config.get_config()) and ('mgi' in config.get_config()['dbauth']))):
            print("ERROR: not configured with PG user/password.")

        #source-specific warnings.  will be cleared when resolved.
        #print("WARN: we are filtering G2P on the wild-type environment data for now")

        return

    def fetch(self):
        '''
        For the MGI resource, we connect to the remote database, and pull the tables into local files.
        We'll check the local table versions against the remote version
        :return:
        '''

        #create the connection details for MGI
        cxn = config.get_config()['dbauth']['mgi']
        cxn.update({'host' : 'adhoc.informatics.jax.org', 'database' : 'mgd', 'port' : 5432 })

        self.dataset.setFileAccessUrl(('').join(('jdbc:postgresql://',cxn['host'],':',str(cxn['port']),'/',cxn['database'])))

        #process the tables
        #self.fetch_from_pgdb(self.tables,cxn,100)  #for testing
        self.fetch_from_pgdb(self.tables,cxn)

        datestamp=ver=None
        #get the resource version information from table mgi_dbinfo, already fetched above
        outfile=('/').join((self.rawdir,'mgi_dbinfo'))

        if os.path.exists(outfile):
            st = os.stat(outfile)
            with open(outfile, 'r') as f:
                f.readline() #read the header row; skip
                info = f.readline()
                cols = info.split('\t')
                ver = cols[0] #col 0 is public_version
                ver = ver.replace('MGI ','')  #MGI 5.20 --> 5.20
                #MGI has a datestamp for the data within the database; use it instead of the download date
                #datestamp in the table: 2014-12-23 00:14:20
                d = cols[7].strip()  #modification date
                datestamp = datetime.strptime(d, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
                f.close()

        self.dataset.setVersion(datestamp,ver)

        return

    def scrub(self):
        #TODO any scrubbing needed for this resource?
        '''
        Perform various data-scrubbing on the raw data files prior to parsing.
        For this resource, this currently includes: (none)
        :return: None
        '''

        #Should the wild type alleles be removed?

        return

    # here we're reading and building a full named graph of this resource, then dumping it all at the end
    # supply a limit if you want to test out parsing the head X lines of the file
    def parse(self, limit=None):
        if (limit is not None):
            print("Only parsing first", limit, "rows of each file")
        print("Parsing files...")

        self._process_gxd_genotype_view(('/').join((self.rawdir,'gxd_genotype_view')),limit)
        self._process_gxd_genotype_summary_view(('/').join((self.rawdir,'gxd_genotype_summary_view')),limit)
        self._process_all_summary_view(('/').join((self.rawdir,'all_summary_view')),limit)
        self._process_all_allele_view(('/').join((self.rawdir,'all_allele_view')),limit)
        self._process_gxd_allele_pair_view(('/').join((self.rawdir,'gxd_allelepair_view')),limit)
        self._process_all_allele_mutation_view(('/').join((self.rawdir,'all_allele_mutation_view')),limit)
        #self._process_mrk_marker_view(('/').join((self.rawdir,'mrk_marker_view')),limit)


        print("Finished parsing.")

        self.load_bindings()
        Assoc().loadObjectProperties(self.graph)

        print("Loaded", len(self.graph), "nodes")
        return


    def _process_gxd_genotype_view(self, raw, limit=None):
        #need to make triples:
        #.  genotype is a class  (or instance?)
        #.  genotype has equivalentClass mgi internal identifier?  -- maybe make the internal identifier an anonymous node?
        #.  genotype subclass of intrinsic_genotype
        #.  genotype has_genomic_background strain_key
        #.  strainkey has_label strain
        #.  strainkey in_taxon taxon_id  #not part of this table
        #.  strainkey is a class (or an instance?)

        gu = GraphUtils(curie_map.get())
        cu = CurieUtil(curie_map.get())
        line_counter = 0
        with open(raw, 'r') as f1:
            f1.readline()  # read the header row; skip
            for line in f1:
                line_counter += 1
                (genotype_key,strain_key,isconditional,note,existsas_key,createdby_key,modifiedby_key,creation_date,
                 modification_date,strain,mgiid,dbname,createdbymodifiedby,existsas,empty) = line.split('\t')

                #we can make these proper methods later
                gt = URIRef(cu.get_uri(mgiid))
                igt = BNode('genotypekey'+genotype_key)
                self.graph.add((gt,OWL['equivalentClass'],igt))
                self.graph.add((gt,RDF['type'],URIRef(cu.get_uri(self.terms['intrinsic_genotype']))))
                istrain = BNode('strainkey'+strain_key)
                #FIXME: change strain from class to term. Background?
                self.graph.add((istrain,RDF['type'],Assoc.OWLCLASS))
                self.graph.add((istrain,RDFS['label'],Literal(strain)))
                self.graph.add((gt,URIRef(cu.get_uri(self.relationship['has_reference_part'])),istrain))
                #temporary assignment to Mus musculus
                self.graph.add((istrain,URIRef(cu.get_uri(self.relationship['in_taxon'])),URIRef(cu.get_uri('NCBITaxon:10090'))))

                if (limit is not None and line_counter > limit):
                    break

        return

    def _process_gxd_genotype_summary_view(self,raw,limit=None):
        #need to make triples:
        #. genotype is a class - redundant?
        #. genotype has equivalent class internalGenotypeID
        #. genotype subclass of intrinsic_genotype - redundant?
        #. genotype has label description

        gu = GraphUtils(curie_map.get())
        cu = CurieUtil(curie_map.get())
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1

                (accession_key,accid,prefixpart,numericpart,logicaldb_key,object_key,mgitype_key,private,preferred,createdby_key,modifiedby_key,
                 creation_date,modification_date,mgiid,subtype,description,short_description) = line.split('\t')
                #note the short_description is the GVC

                #we can make these proper methods later
                gt = URIRef(cu.get_uri(mgiid))
                igt = BNode('genotypekey'+object_key)
                self.graph.add((gt,OWL['equivalentClass'],igt))
                self.graph.add((gt,RDF['type'],URIRef(cu.get_uri(self.terms['intrinsic_genotype']))))
                self.graph.add((gt,RDFS['label'],Literal(description)))  #the 'description' is the full genotype label

                if (limit is not None and line_counter > limit):
                    break

        return

    #NOTE: might be best to process alleles initially from the all_allele_view, as this does not have any repeats of alleles!
    def _process_all_summary_view(self,raw,limit):
        #Need to make triples:
        #. allele is an instance of allele
        #. internalAlleleID has equivalent class as allele
        #. allele has label short_description: Better to use symbol from all_allele_view?
        #. allele has description description

        #TODO: allele subtype

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1

                (accession_key,accid,prefixpart,numericpart,logicaldb_key,object_key,mgitype_key,private,preferred,
                 createdby_key,modifiedby_key,creation_date,modification_date,mgiid,subtype,description,short_description) = line.split('\t')
                #NOTE:May want to filter alleles based on the preferred field (preferred = 1) or will get duplicates
                ## (24288, to be exact... Reduced to 480 if filtered on preferred = 1)
                #NOTE:Decision to make: use the short_description here or use the labels from the allelepair_view?
                #Use this table. allelepair_view will have more repetitions of alleles due to inclusion in genotypes.

                #If we want to filter on preferred:
                if preferred == '1':
                    allele = URIRef(cu.get_uri(mgiid))
                    iallele = BNode('allelekey'+object_key)

                    #allele is a class - No longer needed
                    #self.graph.add((allele,RDF['type'],Assoc.OWLCLASS))
                    #FIXME:allele as subclass - both a class and a subclass? Or one or the other?
                    self.graph.add((allele,RDF['type'],URIRef(cu.get_uri(self.terms['allele']))))
                    #internalAlleleID has an equivalent class allele.
                    #FIXME: sameas instead of equivalentClass. Is this correct?
                    self.graph.add((iallele,OWL['sameAs'],allele))
                    #allele has label short_description
                    #FIXME:Can pull the short_description as a label here, but using the symbol variable in the all_allele_view may be preferable
                    #self.graph.add((allele,RDFS['label'],Literal(short_description)))

                    #. allele has description description
                    self.graph.add((allele,DC['description'],Literal(description)))


                if (limit is not None and line_counter > limit):
                    break

        return


    def _process_all_allele_view(self,raw,limit):
        #NOTE: allele == variant locus
        #Need triples:
        #. (variant) allele is a subclass of variant_locus
        #. (variant) allele is variant_of gene/marker
        #. (wild type) allele is a subclass of reference_locus
        #. (wild type) allele is reference_of gene/marker
        #. allele has label symbol (any reformatting?)
        #. sequence alteration is a class
        #. sequence alteration is a subclass of SO:0001059
        #. sequence alteration has description name
        #. sequence alteration in strain

        # Extra: strain_key, map along the lines of "allele (allele_key -> Bnode) in strain (strain_key -> Bnode)?"
        # Strain label available. Marker label available. Better to map those through their primary tables, correct?
        #TODO
        # Allele type key also available. Need to locate related table
        # transmission_key -> inheritance? Need to locate related table.
        # strain: sequence_alteration in strain?

        #Instead of a function-specific set of variables, should these instead be added
        # to the relationship table at the top?

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1

                (allele_key,marker_key,strain_key,mode_key,allele_type_key,allele_status_key,transmission_key,
                 collection_key,symbol,name,nomensymbol,iswildtype,isextinct,ismixed,createdby_key,modifiedby_key,
                 approvedby_key,approval_date,creation_date,modification_date,markersymbol,term,statusnum,strain,createby,modifiedby,approvedby) = line.split('\t')

                iallele = BNode('allelekey'+allele_key)
                imarker = BNode('markerkey'+marker_key)
                iseqalt = BNode('seqaltkey'+allele_key)  # Any issues with reusing the allele_key as long as we use a different prefix?
                istrain = BNode('strainkey'+strain_key)
                # for non-wild type alleles:
                if iswildtype == '0':
                    # allele is of type: variant_locus
                    self.graph.add((iallele,RDF['type'],URIRef(cu.get_uri(self.terms['variant_locus']))))
                    # allele is variant of gene/marker
                    self.graph.add((imarker,URIRef(cu.get_uri(self.relationship['has_alternate_part'])),iallele))
                #for wild type alleles:
                elif iswildtype == '1':
                    # allele is of type: reference_locus
                    self.graph.add((iallele,RDF['type'],URIRef(cu.get_uri(self.terms['reference_locus']))))
                    # allele is reference of gene/marker
                    self.graph.add((imarker,URIRef(cu.get_uri(self.relationship['has_reference_part'])),iallele))

                #allele has label symbol (any reformatting?)
                #TODO: Need to process symbols not in the %<%> format for the allele symbol
                self.graph.add((iallele,RDFS['label'],Literal(symbol)))

                #sequence alteration has label reformatted(symbol)
                sa_label = symbol
                if re.match(".*<.*>.*", symbol):
                    #print(sa_label)
                    sa_label = re.sub(".*<", "<", symbol)
                    #print(sa_label)
                elif re.match("\+", symbol):
                    #TODO: Check to see if this is the proper handling, as while symbol is just +, marker symbol has entries without any <+>.
                    sa_label = '<+>'
                    #print(sa_label)
                self.graph.add((iallele,RDFS['label'],Literal(symbol)))

                #sequence alteration is a subclass of SO:0001059
                self.graph.add((iseqalt,RDF['type'],URIRef(cu.get_uri(self.terms['sequence_alteration']))))
                #sequence alteration has description name
                self.graph.add((iseqalt,DC['description'],Literal(name)))

                #sequence alteration in strain
                #FIXME: Is this correct? Also, should wild type alleles be excluded?
                #self.graph.add((iseqalt,URIRef(cu.get_uri(self.relationship['in_strain'])),istrain))

                #FIXME: syntax correct for the OIO statement? Tried a few different approaches.
                #Is it better to add OIO:hasExactSynonym to the MGI.py relationships,
                # or call through the Assoc.relationships? Current implementation works, but is it the best/most efficient?
                # My current syntax for the Assoc.relationships results in an error.
                #FIXME: Should the hasExactSynonym be for the allele or the sequence alteration?
                self.graph.add((iallele,URIRef(cu.get_uri(self.relationship['hasExactSynonym'])),Literal(name)))
                #self.graph.add((iallele,OIO['hasExactSynonym'],Literal(symbol)))
                #self.graph.add(iallele,Assoc.relationships('hasExactSynonym'),Literal(symbol))
                #self.graph.add((iallele,cu.get_uri('OIO:hasExactSynonym'),Literal(symbol)))

                if (limit is not None and line_counter > limit):
                    break

        return

    def _process_gxd_allele_pair_view(self,raw,limit):
        #Need triples:
        #. vslc is of type: vslc
        #. genotype has vslc allele_pair_key
        #. vslc has label processed(vslc_label)
        #. vslc has_part allele1
        #. vslc has_part allele2
        #. vslc has_disposition mapped(allelestate)


        #Additional stuff: chromosome, compound? (entries: Top, Not Applicable, Bottom)

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1

                (allelepair_key,genotype_key,allele_key_1,allele_key_2,marker_key,mutantcellline_key_1,mutantcellline_key_2,
                 pairstate_key,compound_key,sequencenum,createdby_key,modifiedby_key,creation_date,modification_date,symbol,
                 chromosome,allele1,allele2,allelestate,compound) = line.split('\t')
                #NOTE: symbol = gene/marker, allele1 + allele2 = VSLC, allele1/allele2 = variant locus, allelestate = zygosity
                #FIXME Need to handle alleles not in the *<*> format, such as many gene traps, induced mutations, and transgenics

                igt = BNode('genotypekey'+genotype_key)
                iallele1 = BNode('allelekey'+allele_key_1)
                iallele2 = BNode('allelekey'+allele_key_2)
                #Need to map the allelestate to a zygosity term
                zygosity = self._map_zygosity(allelestate)
                ivslc = BNode('vslckey'+allelepair_key)
                #FIXME: VSLC label likely needs processing similar to the processing in the all_allele_view
                #FIXME: Handle null alleles for allele2
                vslc_label = (allele1+'/'+allele2)
                #print(vslc_label)

                #. vslc is of type: vslc
                self.graph.add((ivslc,RDF['type'],URIRef(cu.get_uri(self.terms['variant_single_locus_complement']))))

                #. vslc has label processed(vslc_label)
                self.graph.add((ivslc,RDFS['label'],Literal(vslc_label)))

                #genotype has part vslc
                self.graph.add((igt,URIRef(OWL['hasPart']),ivslc))

                #vslc has parts allele1/allele2
                self.graph.add((ivslc,URIRef(OWL['hasPart']),iallele1))
                self.graph.add((ivslc,URIRef(OWL['hasPart']),iallele2))

                #vslc has disposition mapped(allelestate)
                #FIXME: Is this correct?
                # Also, in my concept map I had zygosity as GENO:0000608 - has_zygosity,
                # but I don't see it in my geno.owl file.
                self.graph.add((ivslc,URIRef(cu.get_uri(self.relationship['has_zygosity'])),URIRef(cu.get_uri(zygosity))))
                #print('zygosity is ',zygosity)

                if (limit is not None and line_counter > limit):
                    break

        return

    def _process_all_allele_mutation_view(self,raw,limit):
        #Need triples:
        #. sequence_alteration has_type mutation
        #. sequence_alteration_type_label?

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1

                (allele_key,mutation_key,creation_date,modification_date,mutation) = line.split('\t')

                iseqalt = BNode('seqaltkey'+allele_key)

                #map the sequence_alteration_type
                seq_alt_type = self._map_seq_alt_type(mutation)
                #seq_alt_type is of type mapped(seq_alt_type)
                self.graph.add((iseqalt,RDF['type'],URIRef(cu.get_uri(seq_alt_type))))

                #FIXME: Do we want to map the sequence alteration type to a label?

                if (limit is not None and line_counter > limit):
                    break

        return

    def _process_mrk_marker_view(self,raw,limit):
        #Need triples:
        #. marker is type class
        #. marker has subclass mapped(markertype)
        #. marker has label symbol
        #. marker in_taxon latin_name
        #TODO: process based on status? (official, withdrawn, interim)
        #. map marker_type
        #. marker is of type mapped(markertype)


        #Do we need to process this table? Things that we will gain:
        #marker/gene name (should that be brought in through NCBI Gene?)
        #organism for the marker/gene, including taxon (latin_name)

        #The mgiid for the marker is in the mrk_summary_view. Many duplications

        #Table has
        #marker_key is primary key, no duplicates.
        #May want to filter on status (interim, official, withdrawn)
        #May want to filter on markertype: (Gene, DNA Segment, Pseudogene, QTL, Transgene, Cytogenetic Marker,
        # BAC/YAC end,Complex/Cluster/Region,Other Genome Feature)
        #Make sublcass of markertype


        #Things to process:
        #1. marker

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1

                (marker_key,organism_key,marker_status_key,marker_type_key,curationstate_key,symbol,name,chromosome,
                 cytogenetic_offset,createdby_key,modifiedby_key,creation_date,modification_date,organism,common_name,
                latin_name,status,marker_type,curation_state,created_by,modified_by) = line.split('\t')

                imarker = BNode('markerkey'+marker_key)
                mapped_marker_type = self._map_marker_type(marker_type)


                self.graph.add((imarker,RDF['type'],Assoc.OWLCLASS))
                #self.graph.add((imarker,Assoc.SUBCLASS,URIRef(self.cu.get_uri(construct_id))))
                self.graph.add((imarker,RDFS['label'],Literal(strain)))
                self.graph.add((gt,URIRef(cu.get_uri(has_reference_part)),istrain))

                if (limit is not None and line_counter > limit):
                    break

        return


    def _process_g2p(self, raw, out, g, limit=None):
        '''
        This module currently filters for only wild-type environments, which clearly excludes application
        of morpholinos.  Very stringent filter.  To be updated at a later time.
        :param raw:
        :param out:
        :param g:
        :param limit:
        :return:
        '''
        print("Processing G2P")
        line_counter = 0
        # hardcode
        eco_id = "ECO:0000059"  #experimental_phenotypic_evidence

        #TODO


        return


    def verify(self):
        status = False
        self._verify(self.outfile)
        status = self._verifyowl(self.outfile)

        # verify some kind of relationship that should be in the file
        return status


    #TODO generalize this to a set of utils
    def _getcols(self,cur,table):
        query=(' ').join(("SELECT * FROM",table,"LIMIT 0"))  #for testing
        #print("COMMAND:",query)
        cur.execute(query)
        colnames = [desc[0] for desc in cur.description]
        print("COLS ("+table+"):",colnames)

        return


    def file_len(self,fname):
        with open(fname) as f:
            for i, l in enumerate(f):
                pass
        return i + 1


    #TODO: Finish identifying SO/GENO terms for mappings for those found in MGI
    def _map_seq_alt_type(self, sequence_alteration_type):
        type = None
        type_map = {
            'Deletion': 'SO:0000159',  # deletion
            'Disruption caused by insertion of vector': 'SO:0000667',  # insertion - correct?
            'Duplication': 'SO:1000035',  # duplication
            'Insertion': 'SO:0000667',  # insertion
            'Insertion of gene trap vector': 'SO:0000667',  # insertion - correct?
            'Intergenic deletion': 'SO:0000159',  # deletion
            'Intragenic deletion': 'SO:0000159',  # deletion
            'Inversion': 'SO:1000036',  # inversion
            'Not Applicable': 'SO:0001060',  # sequence variant - correct?
            'Not Specified': 'SO:0001060',  # sequence variant - correct?
            'Nucleotide repeat expansion': 'SO:0000667',  # insertion - correct?
            'Nucleotide substitutions': 'SO:1000002',  # substitution - Correct? Or another term indicating more than one?
            'Other': 'SO:0001060',  # sequence variant - correct?
            'Single point mutation': 'SO:1000008',  # point_mutation
            'Translocation': 'SO:0000199',  # translocation
            'Transposon insertion': 'SO:0000101',  # transposable_element
            'Undefined': 'SO:0001060',  # sequence variant - correct?
            'Viral insertion': 'SO:0000667',  # insertion - correct?
            'wild type': 'SO:0000817'  # wild type
        }
        if (sequence_alteration_type.strip() in type_map):
            type = type_map.get(sequence_alteration_type.strip())
            # type = 'http://purl.obolibrary.org/obo/' + type_map.get(allele_type)
            # print("Mapped: ", sequence_alteration_type, "to", type)
        else:
            # TODO add logging
            print("ERROR: Sequence Alteration Type (", sequence_alteration_type, ") not mapped")

        return type

    def _map_zygosity(self, zygosity):
        type = None
        type_map = {
            'Heterozygous': 'GENO:0000135',
            'Hemizygous Y-linked': 'GENO:0000604',
            'Heteroplasmic': 'GENO:0000603',
            'Homozygous': 'GENO:0000136',
            'Homoplasmic': 'GENO:0000602',
            'Hemizygous Insertion': 'GENO:0000606',
            'Hemizygous Deletion': 'GENO:0000606',  # hemizygous insertion
            #NOTE: GENO:0000606 is  'hemizygous insertion' but is used for the general 'hemizgous' in the Genotype.py file.
            'Hemizygous X-linked': 'GENO:0000605',
            'Indeterminate': 'GENO:0000137'
        }
        if (zygosity.strip() in type_map):
            type = type_map.get(zygosity)
            # type = 'http://purl.obolibrary.org/obo/' + type_map.get(zygosity)
        # print("Mapped: ", allele_type, "to", type)
        else:
            # TODO add logging
            print("ERROR: Allele Type (", zygosity, ") not mapped")

        return type

    def _map_marker_type(self, marker_type):
        type = None
        type_map = {
            'Complex/Cluster/Region': 'SO:0000001',  # region. Something more specific available?
            'Transgene': 'SO:0000902',  # transgene
            'Gene': 'SO:0000704',  # gene
            'QTL': 'SO:0000771',  # QTL
            'DNA Segment': 'SO:0000110',  # sequence_feature. sequence_motif=SO:0001683? region=SO:0000001
            'Pseudogene': 'SO:0000336',  # pseudogene
            'Cytogenetic Marker': 'SO:0001645',  # genetic_marker?
            'Other Genome Feature': 'SO:0000110',  # sequence_feature. Or sequence_motif=SO:0001683?
            'BAC/YAC end': 'SO:0000999',  # BAC_end: SO:0000999, YAC_end: SO:00011498
        }
        if (marker_type.strip() in type_map):
            type = type_map.get(marker_type)
            # type = 'http://purl.obolibrary.org/obo/' + type_map.get(zygosity)
        # print("Mapped: ", allele_type, "to", type)
        else:
            # TODO add logging
            print("ERROR: Marker Type (", marker_type, ") not mapped")

        return type
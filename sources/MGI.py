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

    #USED
    # gxd_genotype_view, gxd_genotype_summary_view, gxd_allelepair_view, all_summary_view,
    # all_allele_view, all_allele_mutation_view, mrk_marker_view, voc_annot_view,
    # voc_evidence_view, bib_acc_view, prb_strain_view

    #NOT YET USED
    # mgi_organism_acc_view: Don't think we need this as I have handled the taxon mapping through a map_taxon function, unless we want the MGI ID for the organism.
    # mgi_organism_view: I mapped the taxon from the mrk_marker_view to include all used organisms, but the mapping could be done in a more complete fashion with this table.
    # mgi_reference_allele_view: Don't believe this view is used in either the genotype of phenotype view
    # all_allele_cellline_view: Don't believe this view is used in either the genotype of phenotype view
    # voc_term_view: Don't believe this view is used in either the genotype of phenotype view
    # mrk_summary_view: Used in genotype view. Only need it if we want the MGI ID for the gene.
    # mgi_note_vocevidence_view: Used in phenotype view for free_text_phenotype_description
    # acc_logicaldb_view: Don't believe this view is used in either the genotype of phenotype view
    # mgi_note_strain_view: Don't believe this view is used in either the genotype of phenotype view
    # FIXME - prb_strain_acc_view: Don't believe this view is used in either the genotype of phenotype view, but is needed if we want the MGI ID for the strain.
    # prb_strain_summary_view: Don't believe this view is used in either the genotype of phenotype view
    # prb_strain_marker_view: Don't believe this view is used in either the genotype of phenotype view

#TODO: QA List
    #Do identifiers have the proper prefixes?
    #Are there quotes that need to be stripped from variables?
    #Is there scrubbing needed for any variables?
    #If present in other functions, can the scrubbing be moved to the scrub function?
    #Make a checklist for the full graph and confirm that all nodes are present.
    #Do we need to do any HTML formatting of labels? (< -> &lt;)

    tables = [
        'mgi_dbinfo',
        'gxd_genotype_view',
        'gxd_genotype_summary_view',
        'gxd_allelepair_view',
        'all_summary_view',
        'all_allele_view',
        'all_allele_mutation_view',
        'mrk_marker_view',
        'voc_annot_view',
        'voc_evidence_view',
        'bib_acc_view',
        'prb_strain_view',
        'mrk_summary_view',
        'mrk_acc_view'
    ]


    relationship = {
        'is_mutant_of' : 'GENO:0000440',
        'derives_from' : 'RO:0001000',
        'has_alternate_part' : 'GENO:0000382',
        'has_reference_part' : 'GENO:0000385',
        'in_taxon' : 'RO:0000216',
        'has_zygosity' : 'GENO:0000608',
        'is_sequence_variant_instance_of' : 'GENO:0000408',
        'hasExactSynonym' : 'OIO:hasExactSynonym',
        'has_disposition' : 'GENO:0000208',
        'has_phenotype' : 'RO:0002200'
    }

    terms = {
        'variant_locus' : 'GENO:0000483',
        'reference_locus' : 'GENO:0000036',
        'sequence_alteration' : 'SO:0001059',
        'variant_single_locus_complement' : 'GENO:0000030',
        'allele' : 'GENO:0000008',
        'intrinsic_genotype' : 'GENO:0000000',
        'phenotype' : 'MONARCH:phenotype',  # Is this correct? What about GENO:0000348 - phenotype? MONARCH:phenotype
        'evidence' : 'MONARCH:evidence',
        'genomic_background' : 'GENO:0000010'
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

    def fetch(self, is_dl_forced):
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
        self._process_mrk_summary_view(('/').join((self.rawdir,'mrk_summary_view')),limit)
        self._process_mrk_marker_view(('/').join((self.rawdir,'mrk_marker_view')),limit)
        self._process_mrk_acc_view(('/').join((self.rawdir,'mrk_acc_view')),limit)
        self._process_voc_annot_view(('/').join((self.rawdir,'voc_annot_view')),limit)
        self._process_voc_evidence_view(('/').join((self.rawdir,'voc_evidence_view')),limit)
        self._process_bib_acc_view(('/').join((self.rawdir,'bib_acc_view')),limit)
        self._process_prb_strain_view(('/').join((self.rawdir,'prb_strain_view')),limit)


        print("Finished parsing.")

        self.load_bindings()
        Assoc().loadObjectProperties(self.graph)

        print("Loaded", len(self.graph), "nodes")
        return


    def _process_gxd_genotype_view(self, raw, limit=None):
        '''
        This table indicates the relationship between a genotype, it's internal+mgi identifier,
        and it's background strain.  Taxon relationships for the strain will be taken care of in another table.

        Makes these triples:
        <MGI:genotypeid> a GENO:genotype
        <MGI:genotypeid> sameAs <internal genotype id>
        <internal strain id> a GENO:genomic_background
        <MGI:genotypeid> GENO:has_reference_part <internal strain id>

        :param raw:
        :param limit:
        :return:
        '''


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
                igt_id = self._makeInternalIdentifier('genotype',genotype_key)
                igt = BNode(igt_id)
                gu.addIndividualToGraph(self.graph,mgiid,None,self.terms['intrinsic_genotype'])
                self.graph.add((gt,OWL['sameAs'],igt))

                istrain_id = self._makeInternalIdentifier('strain',strain_key)
                istrain_node = BNode(istrain_id)
                gu.addIndividualToGraph(self.graph,istrain_id,None,self.terms['genomic_background'])

                self.graph.add((gt,URIRef(cu.get_uri(self.relationship['has_reference_part'])),istrain_node))

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
                igt_id = self._makeInternalIdentifier('genotype',object_key)
                igt_node = BNode(igt_id)
                gu.addIndividualToGraph(self.graph,mgiid,description,self.terms['intrinsic_genotype'])
                self.graph.add((gt,OWL['sameAs'],igt_node))


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
                 approvedby_key,approval_date,creation_date,modification_date,markersymbol,term,statusnum,strain,collection,createdby,modifiedby,approvedby) = line.split('\t')

                iallele = BNode('allelekey'+allele_key)
                imarker = BNode('markerkey'+marker_key)
                iseqalt = BNode('seqaltkey'+allele_key)  # Any issues with reusing the allele_key as long as we use a different prefix?
                istrain = BNode('strainkey'+strain_key)
                #TODO: not using the strain key yet, so need to add that to the graph here. More strain data in the prb_strain_view.

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



    def _process_voc_annot_view(self,raw,limit):
        '''
        This MGI table represents associations between things.
        We currently filter this table on Genotype-Phenotype associations, but may be expanded in the future.
        The table only includes the internal genotype identifiers, so we link on that.

        :param raw:
        :param limit:
        :return:
        '''

        #TODO also get Strain/Attributes (annottypekey = 1000)
        #TODO what is Phenotype (Derived) vs non-derived?  (annottypekey = 1015)
        #TODO is evidence in this table?  what is the evidence vocab key?

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:

                (annot_key,annot_type_key,object_key,term_key,qualifier_key,creation_date,modification_date,qualifier,
                 term,sequence_num,accid,logicaldb_key,vocab_key,mgi_type_key,evidence_vocab_key,anot_type) = line.split('\t')


                # Restricting to type 1002, as done in the MousePhenotypes view.
                # Corresponds to 'Mammalian Phenotype/Genotype' and MP terms
                if annot_type_key == '1002':
                    line_counter += 1

                    #todo add NOT annotations
                    #skip 'normal'
                    if (qualifier=='norm'):
                        print("INFO: found normal phenotype:",term)
                        continue

                    #. This is the phenotype, or MP term for the phenotype.
                    pnode = URIRef(cu.get_uri(accid))
                    gu.addClassToGraph(self.graph,accid,None)

                    #. internalAssociation ID is the annotation_key
                    #. NIF MousePhenotypes view prefixes with MGIAnnotInternal:
                    iassoc_id = self._makeInternalIdentifier('annot',annot_key)

                    assoc_id = self.make_id(iassoc_id)
                    n = URIRef(cu.get_uri(':'+assoc_id))

                    # internalGenotype ID is the object_key
                    gt_id = self._makeInternalIdentifier('genotype',object_key)
                    gtnode = BNode(gt_id)
                    gu.addIndividualToGraph(self.graph,gt_id,None)


                    #add the association
                    assoc = G2PAssoc(':'+assoc_id,gt_id,accid,None,None)
                    assoc.addAssociationNodeToGraph(self.graph)


                if (limit is not None and line_counter > limit):
                    break

        return


    def _process_voc_evidence_view(self,raw,limit):
        '''
        Here we fetch the evidence (code and publication) for the associations.
        :param raw:
        :param limit:
        :return:
        '''

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1

                (annot_evidence_key,annot_key,evidence_term_key,refs_key,inferred_from,created_by_key,modified_by_key,
                creation_date,modification_date,evidence_code,evidence_seq_num,jnumid,jnum,short_citation,created_by,modified_by)= line.split('\t')

                iassoc_id = self._makeInternalIdentifier('annot',annot_key)
                assoc_id = self.make_id(iassoc_id)  #the public version of the identifier

                # Only 18 evidence codes used in MGI, so create a mapping function to map the label and the ID.
                evidence_id = self._map_evidence_id(evidence_code)
                evidence = URIRef(cu.get_uri(evidence_id))

                #TODO add it as an instance of what type?
                #add the pub as an individual;
                gu.addIndividualToGraph(self.graph,jnumid,None)
                pub = URIRef(cu.get_uri(jnumid))

                #add the ECO and citation information to the annot
                self.graph.add((URIRef(cu.get_uri(':'+assoc_id)),DC['evidence'],evidence))
                self.graph.add((URIRef(cu.get_uri(':'+assoc_id)),DC['source'],pub))


                if (limit is not None and line_counter > limit):
                    break

        return


    def _process_bib_acc_view(self,raw,limit):
        '''
        This will make equivalences between the different pub ids
        :param raw:
        :param limit:
        :return:
        '''

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r', encoding="utf8") as csvfile:
            filereader = csv.reader(csvfile, delimiter='\t', quotechar='\"')
            for line in filereader:
                line_counter += 1
                if (line_counter == 1):
                    continue #skip header
                (accession_key,accid,prefixpart,numericpart,logicaldb_key,object_key,mgitype_key,private,preferred,
                created_by_key,modified_by_key,creation_date,modification_date,logical_db)= line

                ipub_id = self._makeInternalIdentifier('publication',object_key)
                ipub = BNode(ipub_id)

                logical_db = logical_db.strip()

                #get the real nice pub identifier
                pub_id = None
                if (logicaldb_key == '29'):  #pubmed
                    pub_id = 'PMID:'+accid
                elif (logicaldb_key == '1' and re.match('J|MGI:',prefixpart)):
                    pub_id = accid
                elif (logical_db == 'Journal Link'):
                    #some DOIs seem to have spaces
                    #FIXME MGI needs to FIX THESE UPSTREAM!!!!
                    #we'll scrub them here for the time being
                    pub_id = 'DOI:'+re.sub('\s+','',accid)

                if (pub_id is not None):
                    #only add these to the graph if it's mapped to something we understand
                    gu.addIndividualToGraph(self.graph,pub_id,None)
                    gu.addIndividualToGraph(self.graph,ipub_id,None)
                    #todo add this to graph utils
                    self.graph.add((ipub,OWL['sameAs'],URIRef(cu.get_uri(pub_id))))

                else:
                    print("WARN: Publication from (", logical_db, ") not mapped for",ipub_id)

                if (limit is not None and line_counter > limit):
                    break

        return

    def _process_prb_strain_view(self,raw,limit):
        '''
        Process a table to get strains (with internal ids), and their labels.
        These strains are created as instances of intrinsic_genotype.

        :param raw:
        :param limit:
        :return:
        '''
        #Only 9 strain types if we want to map them (recombinant congenci, inbred strain, NA, congenic,
        # consomic, coisogenic, recombinant inbred, NS, conplastic)
        #160 species types, but could probably slim that down.
        #If we don't want anything else from this table other than the strain label, could potentially drop it
        # and just keep the strain labelling in the gxd_genotype_view.


        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0

        with open(raw, 'r', encoding="utf8") as csvfile:
            filereader = csv.reader(csvfile, delimiter='\t', quotechar='\"')
            for line in filereader:
                line_counter += 1

                (strain_key,species_key,strain_type_key,strain,standard,private,genetic_background,created_by_key,
                modified_by_key,creation_date,modification_date,species,strain_type,created_by,modified_by) = line

                istrain_id = self._makeInternalIdentifier('strain',strain_key)
                istrain_node = BNode(istrain_id)

                #FIXME is the strain an 'intrinsic_genotype', 'genomic_background' or something else?
                gu.addIndividualToGraph(self.graph,istrain_id,strain,self.terms['intrinsic_genotype'])
                #TODO add species
                #TODO what is strain type anyway?
                #ispecies = BNode('specieskey'+species_key)
                #istrain_type = BNode('straintypekey'+strain_type_key)

                if (limit is not None and line_counter > limit):
                    break

        return


    def _process_mrk_marker_view(self,raw,limit):
        '''
        This is the definition of markers (as in genes, but other genomic loci as well).
        This includes their labels, specific class, and identifiers
        FIXME, it doesn't create real node ids, but BNodes.  will this get rectified?
        TODO should we use the mrk_mouse_view instead?
        :param raw:
        :param limit:
        :return:
        '''
        #Need triples:
        #. marker is type class
        #. marker has subclass mapped(markertype)
        #. marker has label symbol
        #. marker has synonym name
        #. or marker has description name?
        #Process based on status? (official, withdrawn, interim)
        #Do we want the chromosome number?

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

                #Remove the withdrawn markers
                if marker_status_key != '2':

                    imarker_id = self._makeInternalIdentifier('marker',marker_key)
                    imarker_node = BNode(imarker_id)

                    #perhaps only pull info for mouse genes here?  other species should come from other dbs
                    if (organism_key != '1'):
                        continue

                    #map the marker to the gene class
                    mapped_marker_type = self._map_marker_type(marker_type)

                    gu.addClassToGraph(self.graph,imarker_id,symbol,mapped_marker_type,name)
                    gu.addSynonym(self.graph,imarker_id,name,Assoc.relationships['hasExactSynonym'])

                    #add the taxon
                    taxon_id = self._map_taxon(latin_name)
                    self.graph.add((imarker_node,URIRef(cu.get_uri(self.relationship['in_taxon'])),URIRef(cu.get_uri(taxon_id))))

                    #TODO: Think it would make more sense to map the taxon using one of the organism tables.
                    #TODO: If mapping to taxon using an organism table, map to the organism BNode
                    #self.graph.add((imarker,URIRef(cu.get_uri(self.relationship['in_taxon'])),iorganism))

                    if (limit is not None and line_counter > limit):
                        break

        return


    def _process_mrk_summary_view(self,raw,limit):
        #NOTE: There are multiple identifiers available for markers/genes from 28 different resources in this table.
        #Currently handling identifiers from TrEMBL, PDB, ENSEMBL, PRO, miRBASE, MGI, Entrez gene, RefSeq,
        # swiss-prot, and EC, but can add more.

        #Need to grab the iMarker ID, MGI ID
        #Determine if the row is the MGI ID row
            #Process differently if it is. Add to graph as URI?
        #Otherwise process as a non MGI ID row
        #Is it from one of the resources that you wish to use?
            #If so, add as imarker same as marker ID?

        #Need triples:
        #.


        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1

                #print(line.split('\t'))
                (accession_key,accid,prefixpart,numericpart,logicaldb_key,object_key,mgi_type_key,private,preferred,
                 created_by_key,modified_by_key,creation_date,modification_date,mgiid,subtype,description,short_description) = line.split('\t')

                imarker = BNode('markerkey'+object_key)
                mgi_id = URIRef(cu.get_uri(mgiid))


                # Do we need to do specific adjustments for different ID sources?
                if logicaldb_key == '1' and accid == mgiid:
                    #imarker has ID mgiid
                    #print(accid)

                    self.graph.add((mgi_id,OWL['sameAs'],imarker))

                #May only be able to batch a subset of these if performing any
                # specific ID processing for different resources.

                #Need a different approach here. Resulting in mapping to multiple internal marker IDs. Map to the accession key instead?
                #Or maybe not....
                #ISSUE: MirBase accession ID can map to multiple MGI IDs if the miRNA is also part of a cluster (Mirlet7b is part of cluster Mirc31)

                elif logicaldb_key in ['41', '45', '60', '133', '134', '135', '27', '83', '1', '55', '13', '8']: # '27'


                    #Do something
                    if logicaldb_key in ['133','134','60']:
                        accid = 'ENSEMBL:'+accid
                    elif logicaldb_key == '83':
                        accid = 'miRBase:'+accid
                    elif logicaldb_key == '1':
                        accid = 'MGI:'+accid
                    elif logicaldb_key == '41':
                        accid = 'TrEMBL:'+accid
                    elif logicaldb_key == '45':
                        accid = 'PDB:'+accid
                    elif logicaldb_key == '135':
                        accid = 'PR:'+accid
                    elif logicaldb_key == '83':
                        accid = 'miRBase:'+accid
                    elif logicaldb_key == '55':
                        accid = 'NCBIGene:'+accid
                        #FIXME: mark this as an equivalentClass?
                        self.graph.add((imarker,OWL['equivalentClass'],URIRef(cu.get_uri(accid))))
                    elif logicaldb_key == '27':
                        accid = 'RefSeq:'+accid
                    elif logicaldb_key == '13':
                        accid = 'SwissProt:'+accid
                    elif logicaldb_key == '8':
                        accid = 'EC:'+accid
                    #FIXME: The EC IDs are used for multiple genes, resulting in one EC number
                    #Equivalence association for this type?
                    # that then maps to multiple marker IDs.




                    alt_mrk_id = URIRef(cu.get_uri(accid))

                        #FIXME: Since these are alternate IDs,
                    self.graph.add((imarker,OWL['sameAs'],alt_mrk_id))
                    #self.graph.add((alt_mrk_id,OWL['sameAs'],imarker))

                if (limit is not None and line_counter > limit):
                    break

        return

    def _process_mrk_acc_view(self,raw,limit):
        #. Need to grab the NCBI Gene ID for the markers, and use that as an equivalentClass
        #. in order to fill in the empty nodes if there is no match for a marker in the mrk_summary_view.
        #. There are some MGI IDs available, but there may be duplicates or even different IDs
        # for a given marker key(object key), if we want to grab some of those IDs from this table.


        #Need triples:
        #.

        #TODO consider making a pass through the table and making a hash of the internal/primary external key

        gu = GraphUtils(self.namespaces)
        cu = CurieUtil(self.namespaces)
        line_counter = 0
        with open(raw, 'r') as f:
            f.readline()  # read the header row; skip
            for line in f:
                line_counter += 1
                (accession_key,accid,prefix_part,numeric_part,logicaldb_key,object_key,mgi_type_key,private,preferred,
                 created_by_key,modified_by_key,creation_date,modification_date,logicaldb,organism_key) = line.split('\t')

                imark_id = self._makeInternalIdentifier('marker',object_key)

                marker_id = None
                if (preferred == '1'):  #what does it mean if it's 0?
                    if logicaldb_key == '55':  #entrez/ncbi
                        marker_id = 'NCBIGene:'+accid
                    elif logicaldb_key == '1':  #mgi
                        marker_id = accid
                    elif logicaldb_key == '60':
                        marker_id = 'ENSEMBL:'+accid

                if (marker_id is not None):
                    gu.addClassToGraph(self.graph,marker_id,None)
                    gu.addEquivalentClass(self.graph,marker_id,imark_id)

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
        #Need: evidence, publication, association ID, entity ID, phenotype ID
        #Evidence: voc_evidence_view:evidencecode
        #Publication:voc_evidence_view:refs_key -> bib_acc_view.object_key
        #AssociationID:voc_annot_view?:annot_key. NOTE: ZFIN assembles the assoc_id: assoc_id = self.make_id((genotype_id+env_id+phenotype_id+pub_id))
        #NOTE: For MGI, environment is hard coded as a null.
        #EntityID:genotype_id, from annot_view.object_key
        #PhenotypeID:voc_annot_view?:accid

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
            return sum(1 for line in f)


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
            'Complex/Cluster/Region': 'SO:0000001',  # region. Something more specific available? #fixme
            'Transgene': 'SO:0000902',  # transgene
            'Gene': 'SO:0000704',  # gene
            'QTL': 'SO:0000771',  # QTL
            'DNA Segment': 'SO:0000110',  # sequence_feature. sequence_motif=SO:0001683? region=SO:0000001
            'Pseudogene': 'SO:0000336',  # pseudogene
            'Cytogenetic Marker': 'SO:0001645',  # genetic_marker?   #fixme
            'Other Genome Feature': 'SO:0000110',  # sequence_feature. Or sequence_motif=SO:0001683?
            'BAC/YAC end': 'SO:0000150',  # BAC_end: SO:0000999, YAC_end: SO:00011498; using parent term
        }
        if (marker_type.strip() in type_map):
            type = type_map.get(marker_type)
        else:
            print("ERROR: Marker Type (", marker_type, ") not mapped")

        return type

    def _map_taxon(self, taxon_name):
        type = None
        type_map = {
            'Bos taurus': 'NCBITaxon:9913',
            'Canis familiaris': 'NCBITaxon:9615',
            'Capra hircus': 'NCBITaxon:9925',
            'Cavia porcellus': 'NCBITaxon:10141',
            'Cricetulus griseus': 'NCBITaxon:10029',
            'Danio rerio': 'NCBITaxon:7955',
            'Equus caballus': 'NCBITaxon:9796',
            'Felis catus': 'NCBITaxon:9685',
            'Gallus gallus': 'NCBITaxon:9031',
            'Gorilla gorilla': 'NCBITaxon:9593',
            'Homo sapiens': 'NCBITaxon:9606',
            'Macaca mulatta': 'NCBITaxon:9544',
            'Macropus eugenii': 'NCBITaxon:9315',
            'Mesocricetus auratus': 'NCBITaxon:10036',
            'Microcebus murinus': 'NCBITaxon:30608',
            'Mus musculus/domesticus': 'NCBITaxon:10090',  # 10090=Mus musculus, 10092=Mus musculus domesticus
            'Ornithorhynchus anatinus': 'NCBITaxon:9258',
            'Oryctolagus cuniculus': 'NCBITaxon:9986',
            'Ovis aries': 'NCBITaxon:9940',
            'Pan troglodytes': 'NCBITaxon:9598',
            'Pongo pygmaeus': 'NCBITaxon:9600',
            'Rattus norvegicus': 'NCBITaxon:10116',
            'Sus scrofa domestica L.': 'NCBITaxon:9823',  # 9823=Sus scrofa, 9825=Sus scrofa domestica
            'Xenopus (Silurana) tropicalis': 'NCBITaxon:8364',
        }
        if (taxon_name.strip() in type_map):
            type = type_map.get(taxon_name)
            # type = 'http://purl.obolibrary.org/obo/' + type_map.get(zygosity)
        # print("Mapped: ", allele_type, "to", type)
        else:
            # TODO add logging
            print("ERROR: Taxon Name (", taxon_name, ") not mapped")

        return type

    def _map_evidence_id(self, evidence_code):
        #TODO a default evidence code???  what should it be?
        type = None
        type_map = {
            'EXP': 'ECO:0000006',
            'IBA': 'ECO:0000318',
            'IC': 'ECO:0000001',
            'IDA': 'ECO:0000314',
            'IEA': 'ECO:0000501',
            'IEP': 'ECO:0000008',
            'IGI': 'ECO:0000316',
            'IKR': 'ECO:0000320',
            'IMP': 'ECO:0000315',
            'IPI': 'ECO:0000353',
            'ISA': 'ECO:0000200',
            'ISM': 'ECO:0000202',
            'ISO': 'ECO:0000201',
            'ISS': 'ECO:0000250',
            'NAS': 'ECO:0000303',
            'ND': 'ECO:0000035',
            'RCA': 'ECO:0000245',
            'TAS': 'ECO:0000304'
        }
        if (evidence_code.strip() in type_map):
            type = type_map.get(evidence_code)
        else:
            print("ERROR: Evidence code (", evidence_code, ") not mapped")

        return type

    def _map_evidence_label(self, evidence_code):
        type = None
        type_map = {
            'EXP': 'experimental evidence',
            'IBA': 'biological aspect of ancestor evidence used in manual assertion',
            'IC': 'inference from background scientific knowledge',
            'IDA': 'direct assay evidence used in manual assertion',
            'IEA': 'evidence used in automatic assertion',
            'IEP': 'expression pattern evidence',
            'IGI': 'genetic interaction evidence used in manual assertion',
            'IKR': 'phylogenetic determination of loss of key residues evidence used in manual assertion',
            'IMP': 'mutant phenotype evidence used in manual assertion',
            'IPI': 'physical interaction evidence used in manual assertion',
            'ISA': 'sequence alignment evidence',
            'ISM': 'match to sequence model evidence',
            'ISO': 'sequence orthology evidence',
            'ISS': 'sequence similarity evidence used in manual assertion',
            'NAS': 'non-traceable author statement used in manual assertion',
            'ND': 'no biological data found',
            'RCA': 'computational combinatorial evidence used in manual assertion',
            'TAS': 'traceable author statement used in manual assertion'
        }
        if (evidence_code.strip() in type_map):
            type = type_map.get(evidence_code)
            # type = 'http://purl.obolibrary.org/obo/' + type_map.get(zygosity)
        # print("Mapped: ", allele_type, "to", type)
        else:
            # TODO add logging
            print("ERROR: Taxon Name (", evidence_code, ") not mapped")

        return type


    def _makeInternalIdentifier(self,prefix,key):
        '''
        This is a special MGI-to-MONARCH-ism.  MGI tables have unique keys that we use here, but don't want
        to necessarily re-distribute those internal identifiers.  Therefore, we make them into keys in a consistent
        way here.
        :param prefix: the object type to prefix the key with, since the numbers themselves are not unique across tables
        :param key: the number
        :return:
        '''

        return '_'+prefix+'key'+key
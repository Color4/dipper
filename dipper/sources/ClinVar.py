import os
import csv
from stat import *
import re
from datetime import datetime
import gzip
import os.path
import unicodedata
import logging
from dipper.utils import pysed

from dipper.sources.Source import Source
from dipper.models.Dataset import Dataset
from dipper.models.Genotype import Genotype
from dipper.models.G2PAssoc import G2PAssoc
from dipper.models.Assoc import Assoc

from dipper.utils.GraphUtils import GraphUtils
from dipper import curie_map
from dipper import config
from dipper.models.GenomicFeature import Feature, makeChromID

logger = logging.getLogger(__name__)


class ClinVar(Source):
    """
    ClinVar is a host of clinically relevant variants, both directly-submitted and curated from the literature.
    We process the variant_summary file here, which is a digested version of their full xml.  We add all
    variants (and coordinates/build) from their system.
    """

    files = {
        'variant_summary': {
            'file': 'variant_summary.txt.gz',
            'url': 'http://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz'
        },
        'variant_citations': {
            'file': 'variant_citations.txt',
            'url': 'http://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/var_citations.txt'
        }
        # TODO work through xml

    }

    variant_ids = [4288, 4289, 4290, 4291, 4297, 5240, 5241, 5242, 5243, 5244, 5245, 5246, 7105, 8877, 9295, 9296,
                   9297, 9298, 9449, 10361, 10382, 12528, 12529, 12530, 12531, 12532, 14353, 14823, 17232, 17233,
                   17234, 17235, 17236, 17237, 17238, 17239, 17284, 17285, 17286, 17287, 18179, 18180, 18181,
                   37123, 94060, 98004, 98005, 98006, 98008, 98009, 98194, 98195, 98196, 98197, 98198, 100055,
                   112885, 114372, 119244, 128714, 130558, 130559, 130560, 130561, 132146, 132147, 132148, 144375,
                   146588, 147536, 147814, 147936, 152976, 156327, 161457, 162000, 167132]

    def __init__(self, tax_ids=None, gene_ids=None):
        Source.__init__(self, 'clinvar')

        self.tax_ids = tax_ids
        self.gene_ids = gene_ids
        self.filter = 'taxids'
        self.load_bindings()

        self.dataset = Dataset('ClinVar', 'National Center for Biotechnology Information', 
                               'http://www.ncbi.nlm.nih.gov/clinvar/', None,
                               'http://www.ncbi.nlm.nih.gov/About/disclaimer.html',
                               'https://creativecommons.org/publicdomain/mark/1.0/')

        if 'test_ids' not in config.get_config() or 'gene' not in config.get_config()['test_ids']:
            logger.warn("not configured with gene test ids.")
        else:
            self.gene_ids = config.get_config()['test_ids']['gene']

        if 'test_ids' not in config.get_config() or 'disease' not in config.get_config()['test_ids']:
            logger.warn("not configured with disease test ids.")
        else:
            self.disease_ids = config.get_config()['test_ids']['disease']

        self.properties = Feature.properties

        return

    def fetch(self, is_dl_forced=False):

        # note: version set from the file date
        self.get_files(is_dl_forced)

        return

    def scrub(self):
        """
        The var_citations file has a bad row in it with > 6 cols.  I will comment these out.

        :return:
        """
        # awk  -F"\t" '{if (NF <= 6) print $1, $2, $3, $4, $5, $6 ; OFS = "\t"}' variant_citations.txt
        f = '/'.join((self.rawdir, self.files['variant_citations']['file']))
        logger.info('removing the line that has too many cols (^15091)')
        pysed.replace("^15091", '#15091', f)

        return

    def parse(self, limit=None):
        if limit is not None:
            print("Only parsing first", limit, "rows")

        self.scrub()

        logger.info("Parsing files...")

        if self.testOnly:
            self.testMode = True

        self._get_variants(limit)
        self._get_var_citations(limit)

        self.load_core_bindings()
        self.load_bindings()

        print("Done parsing files.")

        return

    def _get_variants(self, limit):
        """
        Currently loops through the variant_summary file.

        :param limit:
        :return:
        """
        gu = GraphUtils(curie_map.get())

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        geno = Genotype(g)
        gu.loadAllProperties(g)
        f = Feature(None,None,None)
        f.loadAllProperties(g)
        Assoc().loadAllProperties(g)

        # add the taxon and the genome
        tax_num = '9606'  # HARDCODE
        tax_id = 'NCBITaxon:'+tax_num
        tax_label = 'Human'
        gu.addClassToGraph(g, tax_id, None)
        geno.addGenome(tax_id, None)  #label gets added elsewhere

        # not unzipping the file
        logger.info("Processing Variant records")
        line_counter = 0
        myfile = '/'.join((self.rawdir, self.files['variant_summary']['file']))
        print("FILE:", myfile)
        with gzip.open(myfile, 'rb') as f:
            for line in f:
                # skip comments
                line = line.decode().strip()
                if re.match('^#', line):
                    continue
                # AlleleID               integer value as stored in the AlleleID field in ClinVar  (//Measure/@ID in the XML)
                # Type                   character, the type of variation
                # Name                   character, the preferred name for the variation
                # GeneID                 integer, GeneID in NCBI's Gene database
                # GeneSymbol             character, comma-separated list of GeneIDs overlapping the variation
                # ClinicalSignificance   character, comma-separated list of values of clinical significance reported for this variation
                #                          for the mapping between the terms listed here and the integers in the .VCF files, see
                #                          http://www.ncbi.nlm.nih.gov/clinvar/docs/clinsig/
                # RS# (dbSNP)            integer, rs# in dbSNP
                # nsv (dbVar)            character, the NSV identifier for the region in dbVar
                # RCVaccession           character, list of RCV accessions that report this variant
                # TestedInGTR            character, Y/N for Yes/No if there is a test registered as specific to this variation in the NIH Genetic Testing Registry (GTR)
                # PhenotypeIDs           character, list of db names and identifiers for phenotype(s) reported for this variant
                # Origin                 character, list of all allelic origins for this variation
                # Assembly               character, name of the assembly on which locations are based
                # Chromosome             character, chromosomal location
                # Start                  integer, starting location, in pter->qter orientation
                # Stop                   integer, end location, in pter->qter orientation
                # Cytogenetic            character, ISCN band
                # ReviewStatus           character, highest review status for reporting this measure. For the key to the terms,
                #                            and their relationship to the star graphics ClinVar displays on its web pages,
                #                            see http://www.ncbi.nlm.nih.gov/clinvar/docs/variation_report/#interpretation
                # HGVS(c.)               character, RefSeq cDNA-based HGVS expression
                # HGVS(p.)               character, RefSeq protein-based HGVS expression
                # NumberSubmitters       integer, number of submissions with this variant
                # LastEvaluated          datetime, the latest time any submitter reported clinical significance
                # Guidelines             character, ACMG only right now, for the reporting of incidental variation in a Gene
                #                                (NOTE: if ACMG, not a specific to the allele but to the Gene)
                # OtherIDs               character, list of other identifiers or sources of information about this variant
                # VariantID              integer, the value used to build the URL for the current default report,
                #                            e.g. http://www.ncbi.nlm.nih.gov/clinvar/variation/1756/
                #

                (allele_num, allele_type, allele_name, gene_num, gene_symbol, clinical_significance,
                 dbsnp_num, dbvar_num, rcv_num, tested_in_gtr, phenotype_ids, origin,
                 assembly, chr, start, stop, cytogenetic_loc,
                 review_status, hgvs_c, hgvs_p, number_of_submitters, last_eval,
                 guidelines, other_ids, variant_num) = line.split('\t')

                # #### set filter=None in init if you don't want to have a filter
                # if self.filter is not None:
                #    if ((self.filter == 'taxids' and (int(tax_num) not in self.tax_ids))
                #            or (self.filter == 'geneids' and (int(gene_num) not in self.gene_ids))):
                #        continue
                # #### end filter

                # print(line)

                line_counter += 1

                pheno_list = []
                if phenotype_ids != '-':
                    # trim any leading/trailing semicolons/commas
                    phenotype_ids = re.sub('^[;,]', '', phenotype_ids)
                    phenotype_ids = re.sub('[;,]$', '', phenotype_ids)
                    pheno_list = re.split('[,;]', phenotype_ids)

                if self.testMode:
                    # get intersection of test disease ids and these phenotype_ids
                    intersect = list(set([str(i) for i in self.disease_ids]) & set(pheno_list))
                    if int(gene_num) not in self.gene_ids and int(variant_num) not in self.variant_ids \
                            and len(intersect) < 1 :
                        continue

                # TODO may need to switch on assembly to create correct assembly/build identifiers
                build_id = ':'.join(('NCBIGenome', assembly))

                # make the reference genome build
                geno.addReferenceGenome(build_id, assembly, tax_id)

                allele_type_id = self._map_type_of_allele(allele_type)

                if str(chr) == '':
                    pass
                else:
                    # add the human chromosome class to the graph, and add the build-specific version of it
                    chr_id = makeChromID(str(chr), tax_num)
                    geno.addChromosomeClass(str(chr), tax_id, tax_label)
                    geno.addChromosomeInstance(str(chr), build_id, assembly, chr_id)
                    chrinbuild_id = makeChromID(str(chr), assembly)

                seqalt_id = ':'.join(('ClinVarVariant', variant_num))
                gene_id = ':'.join(('NCBIGene', gene_num))

                # note that there are some "variants" that are actually haplotypes:
                # for example, variant_num = 38562
                # so the dbsnp or dbvar should probably be primary, and the variant num be the vslc,
                # with each of the dbsnps being added to it

                # todo clinical significance needs to be mapped to a list of terms
                # first, make the variant:
                f = Feature(seqalt_id, allele_name, allele_type_id)

                if start != '-' and start.strip() != '':
                    f.addFeatureStartLocation(start, chrinbuild_id)
                if stop != '-' and stop.strip() != '':
                    f.addFeatureEndLocation(stop, chrinbuild_id)

                f.addFeatureToGraph(g)

                # CHECK - this makes the assumption that there is only one affected chromosome per variant
                # what happens with chromosomal rearrangement variants?  shouldn't both chromosomes be here?

                # add the hgvs as synonyms
                if hgvs_c != '-' and hgvs_c.strip() != '':
                    gu.addSynonym(g, seqalt_id, hgvs_c)
                if hgvs_p != '-' and hgvs_p.strip() != '':
                    gu.addSynonym(g, seqalt_id, hgvs_p)

                # add the dbsnp and dbvar ids as equivalent
                if dbsnp_num != '-':
                    dbsnp_id = 'dbSNP:rs'+dbsnp_num
                    gu.addIndividualToGraph(g, dbsnp_id, None)
                    gu.addSameIndividual(g, seqalt_id, dbsnp_id)
                if dbvar_num != '-':
                    dbvar_id = 'dbVar:'+dbvar_num
                    gu.addIndividualToGraph(g, dbvar_id, None)
                    gu.addSameIndividual(g, seqalt_id, dbvar_id)

                # TODO - not sure if this is right... add as xref?
                # the rcv is like the combo of the phenotype with the variant
                # if rcv_num != '-':
                #    rcv_id = 'ClinVar:'+rcv_num
                #    gu.addIndividualToGraph(g,rcv_id,None)
                #    gu.addEquivalentClass(g,seqalt_id,rcv_id)

                # add the gene
                gu.addClassToGraph(g, gene_id, gene_symbol)

                gu.addTriple(g, seqalt_id, geno.object_properties['is_sequence_variant_instance_of'], gene_id)
                # make the variant locus
                # vl_id = ':'+gene_id+'-'+variant_num
                # geno.addSequenceAlterationToVariantLocus(seqalt_id,vl_id)
                # geno.addAlleleOfGene(seqalt_id,gene_id,geno.properties['has_alternate_part'])

                # parse the list of "phenotypes" which are diseases.  add them as an association
                # ;GeneReviews:NBK1440,MedGen:C0392514,OMIM:235200,SNOMED CT:35400008;MedGen:C3280096,OMIM:614193;MedGen:CN034317,OMIM:612635;MedGen:CN169374
                # the list is both semicolon delimited and comma delimited, but i don't know why!
                if phenotype_ids != '-':
                    for p in pheno_list:
                        if re.match('Orphanet:ORPHA', p):
                            p = re.sub('Orphanet:ORPHA', 'Orphanet:', p)
                        elif re.match('SNOMED CT', p):
                            p = re.sub('SNOMED CT', 'SNOMED', p)
                        assoc_id = self.make_id(seqalt_id+p.strip())
                        assoc = G2PAssoc(assoc_id, seqalt_id, p.strip(), None, None)
                        assoc.addAssociationToGraph(g)

                if other_ids != '-':
                    id_list = other_ids.split(',')
                    # process the "other ids"
                    # ex: CFTR2:F508del,HGMD:CD890142,OMIM Allelic Variant:602421.0001
                    # TODO make xrefs
                    for xrefid in id_list:
                        prefix = xrefid.split(':')[0].strip()
                        if prefix == 'OMIM Allelic Variant':
                            xrefid = 'OMIM:'+xrefid.split(':')[1]
                            gu.addIndividualToGraph(g, xrefid, None)
                            gu.addSameIndividual(g, seqalt_id, xrefid)
                        elif prefix == 'HGMD':
                            gu.addIndividualToGraph(g, xrefid, None)
                            gu.addSameIndividual(g, seqalt_id, xrefid)
                        elif prefix == 'dbVar' and dbvar_num == xrefid.split(':')[1].strip():
                            pass  #skip over this one
                        elif re.search('\s', prefix):
                            pass
                            # logger.debug('xref prefix has a space: %s', xrefid)
                        else:
                            # should be a good clean prefix
                            # note that HGMD variants are in here as Xrefs because we can't resolve URIs for them
                            # logger.info("Adding xref: %s", xrefid)
                            # gu.addXref(g, seqalt_id, xrefid)
                            # logger.info("xref prefix to add: %s", xrefid)
                            pass

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return

    def _get_var_citations(self, limit):

        # Generated weekly, the first of the week
        # A tab-delimited report of citations associated with data in ClinVar, connected to the AlleleID, the VariationID, and either rs# from dbSNP or nsv in dbVar.
        #
        # AlleleID          integer value as stored in the AlleleID field in ClinVar  (//Measure/@ID in the XML)
        # VariationID       The identifier ClinVar uses to anchor its default display. (in the XML,  //MeasureSet/@ID)
        # rs			    rs identifier from dbSNP
        # nsv				nsv identifier from dbVar
        # citation_source	The source of the citation, either PubMed, PubMedCentral, or the NCBI Bookshelf
        # citation_id		The identifier used by that source

        gu = GraphUtils(curie_map.get())
        logger.info("Processing Citations for variants")
        line_counter = 0
        myfile = '/'.join((self.rawdir, self.files['variant_citations']['file']))
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph

        with open(myfile, 'r', encoding="utf8") as f:
            filereader = csv.reader(f, delimiter='\t', quotechar='\"')

            for line in filereader:
                # skip comments
                line = line
                if re.match('^#', line[0]):
                    continue
                (allele_num, variant_num, rs_num, nsv_num, citation_source, citation_id) = line

                line_counter += 1

                if self.testMode:
                    if int(variant_num) not in self.variant_ids:
                        continue

                # the citation for a variant is made to some kind of combination of the ids here.
                # but i'm not sure which we don't know what the citation is for exactly, other
                # than the variant.  so use mentions

                var_id = 'ClinVarVariant:'+variant_num

                # citation source: PubMed | PubMedCentral | citation_source
                # citation id:
                # format the citation id:
                ref_id = None
                if citation_source == 'PubMed':
                    ref_id = 'PMID:'+str(citation_id)
                elif citation_source == 'PubMedCentral':
                    ref_id = 'PMCID:'+str(citation_id)
                if ref_id is not None:
                    gu.addTriple(g, ref_id, self.properties['is_about'], var_id)

                if not self.testMode and (limit is not None and line_counter > limit):
                    break

        return

    def _map_type_of_allele(self, alleletype):
        # TODO this will get deprecated when we parse the xml file
        so_id = 'SO:0001060'
        type_to_so_map = {
            'NT expansion': 'SO:1000039',  # direct tandem duplication
            'copy number gain': 'SO:0001742',
            'copy number loss': 'SO:0001743',
            'deletion': 'SO:0000159',
            'duplication': 'SO:1000035',
            'fusion': 'SO:0000806',
            'indel': 'SO:1000032',
            'insertion': 'SO:0000667',
            'inversion': 'SO:1000036',
            'protein only': 'SO:0001580',   # coding sequence variant.  check me
            'short repeat': 'SO:0000657',   # repeat region - not sure if this is what's intended.
            'single nucleotide variant': 'SO:0001483',
            'structural variant': 'SO:0001537',
            'undetermined variant': 'SO:0001060'    # sequence variant
        }

        if alleletype in type_to_so_map:
            so_id = type_to_so_map.get(alleletype)
        else:
            logger.warn("unmapped code %s. Defaulting to 'SO:sequence_variant'.", alleletype)

        return so_id

    def remove_control_characters(self, s):
        # TODO move this into utils function
        return "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")


    def getTestSuite(self):
        import unittest
        from tests.test_clinvar import ClinVarTestCase
        #TODO add G2PAssoc, Genotype tests

        test_suite = unittest.TestLoader().loadTestsFromTestCase(ClinVarTestCase)

        return test_suite
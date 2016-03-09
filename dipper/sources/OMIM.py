import logging
import urllib
import re
import time
from datetime import datetime
import json
from subprocess import call

from dipper.sources.Source import Source
from dipper.models.Dataset import Dataset
from dipper.models.assoc.G2PAssoc import G2PAssoc
from dipper.models.Genotype import Genotype
from dipper.models.GenomicFeature import Feature, makeChromID
from dipper.models.Reference import Reference
from dipper.utils.GraphUtils import GraphUtils
from dipper.utils.DipperUtil import DipperUtil
from dipper import config
from dipper import curie_map
from dipper.utils.romanplus import romanNumeralPattern, fromRoman, toRoman


logger = logging.getLogger(__name__)


class OMIM(Source):
    """
     OMIM is an unusual source.
     We get lots of the disease-gene associations, including allelic variants
     from their ftp site, which is obtainable anonymously.
     However, more detailed information is available via their API.
     So, we pull the basic files from their ftp site,
     extract the omim identifiers, then query their API in batch.
     (Note this requires an apiKey, which is not stored in the repo,
        but in a separate conf.json file.)
     Processing this source serves two purposes:
     1.  enables the creation of the OMIM classes for the purposes of merging
            into the disease ontology
     2.  adds annotations such as disease-gene associations

     When creating the disease classes, we pull from their REST-api
        id/label/definition information.
     Additionally we pull the Orphanet and UMLS mappings
     (to make equivalent ids).
     We also pull the phenotypic series annotations as grouping classes.

     Note that ... ???

    """

    files = {
        'all': {
            'file': 'omim.txt.Z',
            'url': 'ftp://anonymous:info%40monarchinitiative.org@ftp.omim.org/OMIM/omim.txt.Z'},
        'morbidmap': {
            'file': 'morbidmap.txt',
            'url': 'ftp://anonymous:info%40monarchinitiative.org@ftp.omim.org/OMIM/morbidmap'},
        'phenotypicSeries': {
            'file': 'phenotypicSeriesTitles.txt',
            'url': 'http://www.omim.org/phenotypicSeriesTitle/all?format=tab',
            'headers': {'User-Agent': 'Mozilla/5.0'}}
    }

    # TODO PYLINT
    # 2016-FEB  The only file OMIM makes freely available (w/o permission) is:
    # http://omim.org/static/omim/data/mim2gene.txt
    # which has:
    # MIM_numbers, NCBI_Gene_IDs, Ensembl_Gene IDs, HGNC_Gene_Symbols
    # it may be sufficient to replace the missing omim.txt


    # the following test ids are in the config.json
    test_ids = [
        119600, 120160, 157140, 158900, 166220, 168600, 219700,
        253250, 305900, 600669, 601278, 602421, 605073, 607822,   # coriell
        102560, 102480, 100678, 102750, 600201,                   # genes
        104200, 105400, 114480, 115300, 121900,                   # phenotype/disease -- indicate that here?
        107670, 11600, 126453,                                    # gene of known sequence and has a phenotype
        102150, 104000, 107200, 100070, 611742, 611100,
        102480]           # disease with known locus

    OMIM_API = "http://api.omim.org/api"

    def __init__(self):
        Source.__init__(self, 'omim')

        self.load_bindings()

        self.dataset = Dataset('omim', 'Online Mendelian Inheritance in Man',
                               'http://www.omim.org', None,
                               'http://omim.org/help/agreement')

        self.gu = GraphUtils(curie_map.get())

        self.omim_ncbigene_idmap = {}

        # data-source specific warnings
        # (will be removed when issues are cleared)

        # check if config exists; if it doesn't, error out and let user know
        if 'keys' not in config.get_config() and 'omim' not in config.get_config()['keys']:
            logger.error("not configured with API key.")

        # check to see if there's any ids configured in the config;
        # otherwise, warn
        if 'test_ids' not in config.get_config() or 'disease' not in config.get_config()['test_ids']:
            logger.warning("not configured with disease test ids.")
        else:
            # select ony those test ids that are omim's.
            self.test_ids += [obj.replace('OMIM:', '') for obj in config.get_config()['test_ids']['disease']
                              if re.match(r'OMIM:', obj)]

        return

    def fetch(self, is_dl_forced=False):
        """
        Get the preconfigured static files.
        This DOES NOT fetch the individual records via REST...that is handled
        in the parsing function.  (To be refactored.)
        :param is_dl_forced:
        :return:
        """
        self.get_files(is_dl_forced)

        return

    def parse(self, limit=None):
        if limit is not None:
            logger.info("Only parsing first %d rows", limit)

        logger.info("Parsing files...")

        if self.testOnly:
            self.testMode = True

        self._process_all(limit)
        self._process_morbidmap(limit)
        self._process_phenotypicseries(limit)

        self.load_core_bindings()
        self.load_bindings()

        logger.info("Done parsing.")

        return

    def _get_omim_ids(self):
        omimids = []

        # an omim-specific thing here; from the omim.txt.gz file,
        # get the omim numbers
        # not unzipping the file
        logger.info("Obtaining OMIM record identifiers")
        line_counter = 0
        omimfile = '/'.join((self.rawdir, self.files['all']['file']))
        logger.info("FILE: %s", omimfile)
        # TODO check to see if the file is there
        call(["uncompress", omimfile])
        omimfile = omimfile.replace('.Z', '')
        with open(omimfile, "r") as f:
            for line in f:
                line = line.strip()

                if line == "*FIELD* NO":
                    line_counter += 1
                    # read the next line
                    number = f.readline().strip()
                    omimids.append(number)

        # recompress the file
        call(["compress", omimfile])
        logger.info("Done.  I found %d omim ids", omimids.__len__())
        return omimids

    def process_entries(self, omimids, transform,
                        included_fields=None, graph=None, limit=None):
        """
        Given a list of omim ids,
        this will use the omim API to fetch the entries, according to the
        ```included_fields``` passed as a parameter.
        If a transformation function is supplied,
        this will iterate over each entry,
        and either add the results to the supplied ```graph```
        or will return a set of processed entries that the calling function
        can further iterate.

        If no ```included_fields``` are provided, this will simply fetch
        the basic entry from omim,
        which includes an entry's:  prefix, mimNumber, status, and titles.

        :param omimids: the set of omim entry ids to fetch using their API
        :param transform: Function to transform each omim entry when looping
        :param included_fields: A set of what fields are required to retrieve
         from the API
        :param graph: the graph to add the transformed data into
        :return:
        """

        omimparams = {
            'format': 'json'
        }

        # add the included_fields as parameters
        if included_fields is not None and len(included_fields) > 0:
            omimparams['include'] = ','.join(included_fields)

        # you will need to add the API key into the conf.json file, like:
        # keys : { 'omim' : '<your api key here>' }
        omimparams.update({'apiKey': config.get_config()['keys']['omim']})

        gu = GraphUtils(curie_map.get())
        processed_entries = list()

        # scrub any omim prefixes from the omimids before processing
        cleanomimids = set()
        for o in omimids:
            scrubbed = re.sub(r'O?MIM:', '', str(o))
            if re.match(r'\d+', str(scrubbed)):
                cleanomimids.add(scrubbed)
        omimids = list(cleanomimids)

        it = 0  # for counting

        # note that you can only do request batches of 20
        # see info about "Limits" at http://omim.org/help/api
        groupsize = 20
        if not self.testMode and limit is not None:
            # just in case the limit is larger than the number of records,
            # max it out
            maxit = min((limit, omimids.__len__()))
        else:
            maxit = omimids.__len__()

        while it < maxit:
            end = min((maxit, it+groupsize))
            # iterate through the omim ids list,
            # and fetch from the OMIM api in batches of 20

            if self.testMode:
                intersect = list(set([str(i) for i in self.test_ids]) & set(omimids[it:end]))
                # some of the test ids are in the omimids
                if len(intersect) > 0:
                    logger.info("found test ids: %s", intersect)
                    omimparams.update({'mimNumber': ','.join(intersect)})
                else:
                    it += groupsize
                    continue
            else:
                omimparams.update({'mimNumber': ','.join(omimids[it:end])})

            p = urllib.parse.urlencode(omimparams)
            url = '/'.join((self.OMIM_API, 'entry'))+'?%s' % p
            logger.info('fetching: %s', '/'.join((self.OMIM_API, 'entry'))+'?%s' % p)

            # print ('fetching:',(',').join(omimids[it:end]))
            # print('url:', url)

            # TODO try/catch
            d = urllib.request.urlopen(url)
            resp = d.read().decode()
            request_time = datetime.now()
            it += groupsize

            myjson = json.loads(resp)
            entries = myjson['omim']['entryList']

            for e in entries:
                # apply the data transformation, and save it to the graph
                processed_entry = transform(e, graph)
                if processed_entry is not None:
                    processed_entries.append(processed_entry)

                # ### end iterating over batch of entries

            # can't have more than 4 req per sec,
            # so wait the remaining time, if necessary
            dt = datetime.now() - request_time
            rem = 0.25 - dt.total_seconds()
            if rem > 0:
                logger.info("waiting %d sec", rem)
                time.sleep(rem/1000)

        if graph is not None:
            gu.loadAllProperties(graph)

        return processed_entries

    def _process_all(self, limit):
        """
        This takes the list of omim identifiers from the omim.txt.Z file,
        and iteratively queries the omim api for the json-formatted data.
        This will create OMIM classes, with the label,
        definition, and some synonyms.
        If an entry is "removed",
            it is added as a deprecated class.
        If an entry is "moved",
            it is deprecated and consider annotations are added.

        Additionally, we extract:
        *phenotypicSeries ids as superclasses
        *equivalent ids for Orphanet and UMLS

        If set to testMode,
            it will write only those items in the test_ids to the testgraph.

        :param limit:
        :return:
        """
        omimids = self._get_omim_ids()  # store the set of omim identifiers

        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph
        geno = Genotype(g)
        # tax_num = '9606'   # TODO PYLINT unused
        tax_id = 'NCBITaxon:9606'
        tax_label = 'Human'

        # add genome and taxon
        geno.addGenome(tax_id, tax_label)   # tax label can get added elsewhere
        self.gu.addClassToGraph(g, tax_id, None)   # label added elsewhere

        includes = set()
        includes.add('all')

        self.process_entries(omimids, self._transform_entry, includes, g, limit)

        self.gu.loadAllProperties(g)

        return

    def _transform_entry(self, e, graph):
        gu = self.gu
        g = graph
        geno = Genotype(graph)

        tax_num = '9606'
        tax_id = 'NCBITaxon:9606'
        tax_label = 'Human'
        build_num = "GRCh38"
        build_id = "NCBIGenome:"+build_num

        # get the numbers, labels, and descriptions
        omimnum = e['entry']['mimNumber']
        titles = e['entry']['titles']
        label = titles['preferredTitle']

        other_labels = []
        if 'alternativeTitles' in titles:
            other_labels += self._get_alt_labels(titles['alternativeTitles'])
        if 'includedTitles' in titles:
            other_labels += self._get_alt_labels(titles['includedTitles'])

        # add synonyms of alternate labels
        # preferredTitle": "PFEIFFER SYNDROME",
        # "alternativeTitles":
        #   "ACROCEPHALOSYNDACTYLY, TYPE V; ACS5;;\nACS V;;\nNOACK SYNDROME",
        # "includedTitles":
        #   "CRANIOFACIAL-SKELETAL-DERMATOLOGIC DYSPLASIA, INCLUDED"

        # remove the abbreviation (comes after the ;) from the preferredTitle,
        # and add it as a synonym
        abbrev = None
        if len(re.split(r';', label)) > 1:
            abbrev = (re.split(r';', label)[1].strip())
        newlabel = self._cleanup_label(label)

        description = self._get_description(e['entry'])
        omimid = 'OMIM:'+str(omimnum)

        if e['entry']['status'] == 'removed':
            gu.addDeprecatedClass(g, omimid)
        else:
            omimtype = self._get_omimtype(e['entry'])
            nodelabel = newlabel
            # this uses our cleaned-up label
            if omimtype == Genotype.genoparts['heritable_phenotypic_marker']:
                if abbrev is not None:
                    nodelabel = abbrev
                # in this special case,
                # make it a disease by not declaring it as a gene/marker
                gu.addClassToGraph(g, omimid, nodelabel, None, newlabel)
            elif omimtype == Genotype.genoparts['gene']:
                if abbrev is not None:
                    nodelabel = abbrev
                gu.addClassToGraph(g, omimid, nodelabel, omimtype, newlabel)
            else:
                gu.addClassToGraph(g, omimid, newlabel, omimtype)

            # add the original screaming-caps OMIM label as a synonym
            gu.addSynonym(g, omimid, label)

            # add the alternate labels and includes as synonyms
            for l in other_labels:
                gu.addSynonym(g, omimid, l, 'OIO:hasRelatedSynonym')

            # for OMIM, we're adding the description as a definition
            gu.addDefinition(g, omimid, description)
            if abbrev is not None:
                gu.addSynonym(g, omimid, abbrev, 'OIO:hasRelatedSynonym')

            # if this is a genetic locus (but not sequenced)
            #   then add the chrom loc info
            # but add it to the ncbi gene identifier,
            # not to the omim id (we reserve the omim id to be the phenotype)
            feature_id = None
            feature_label = None
            if 'geneMapExists' in e['entry'] and e['entry']['geneMapExists']:
                genemap = e['entry']['geneMap']
                is_gene = False

                if omimtype == Genotype.genoparts['heritable_phenotypic_marker']:
                    # get the ncbigene ids
                    ncbifeature = self._get_mapped_gene_ids(e['entry'], g)
                    if len(ncbifeature) == 1:
                        feature_id = 'NCBIGene:'+str(ncbifeature[0])
                        # add this feature as a cause for the omim disease
                        # TODO SHOULD I EVEN DO THIS HERE?
                        assoc = G2PAssoc(self.name, feature_id, omimid)
                        assoc.add_association_to_graph(g)

                    elif len(ncbifeature) > 1:
                        logger.info(
                            "Its ambiguous when %s maps to >1 gene id: %s",
                            omimid, str(ncbifeature))
                    else:  # no ncbi feature, make an anonymous one
                        feature_id = self._make_anonymous_feature(str(omimnum))
                        feature_label = abbrev

                elif omimtype == Genotype.genoparts['gene']:
                    feature_id = omimid
                    is_gene = True
                else:
                    # 158900 falls into this category
                    feature_id = self._make_anonymous_feature(str(omimnum))
                    if abbrev is not None:
                        feature_label = abbrev
                    omimtype = Genotype.genoparts['heritable_phenotypic_marker']

                if feature_id is not None:
                    if 'comments' in genemap:
                        # add a comment to this feature
                        comment = genemap['comments']
                        if comment.strip() != '':
                            gu.addDescription(g, feature_id, comment)
                    if 'cytoLocation' in genemap:
                        cytoloc = genemap['cytoLocation']
                        # parse the cytoloc.
                        # add this omim thing as a subsequence of the cytofeature
                        # 18p11.3-p11.2
                        # FIXME
                        # add the other end of the range,
                        # but not sure how to do that
                        # not sure if saying subsequence of feature
                        # is the right relationship

                        f = Feature(feature_id, feature_label, omimtype)
                        if 'chromosomeSymbol' in genemap:
                            chrom_num = str(genemap['chromosomeSymbol'])
                            chrom = makeChromID(chrom_num, tax_num, 'CHR')
                            geno.addChromosomeClass(chrom_num, tax_id, tax_label)

                            # add the positional information, if available
                            fstart = fend = -1
                            if 'chromosomeLocationStart' in genemap:
                                fstart = genemap['chromosomeLocationStart']
                            if 'chromosomeLocationEnd' in genemap:
                                fend = genemap['chromosomeLocationEnd']
                            if fstart >= 0:
                                # make the build-specific chromosome
                                chrom_in_build = makeChromID(chrom_num,
                                                             build_num,
                                                             'MONARCH')
                                # then, add the chromosome instance
                                # (from the given build)
                                geno.addChromosomeInstance(chrom_num,
                                                           build_id,
                                                           build_num,
                                                           chrom)
                                if omimtype == Genotype.genoparts['heritable_phenotypic_marker']:
                                    postypes = [Feature.types['FuzzyPosition']]
                                else:
                                    postypes = None
                                # NOTE that no strand information
                                # is available in the API
                                f.addFeatureStartLocation(fstart,
                                                          chrom_in_build,
                                                          None,
                                                          postypes)
                                if fend >= 0:
                                    f.addFeatureEndLocation(fend,
                                                            chrom_in_build,
                                                            None,
                                                            postypes)
                                if fstart > fend:
                                    logger.info("start>end (%d>%d) for %s",
                                                fstart, fend, omimid)
                            # add the cytogenic location too
                            # for now, just take the first one
                            cytoloc = cytoloc.split('-')[0]
                            loc = makeChromID(cytoloc, tax_num, 'CHR')
                            gu.addClassToGraph(g, loc, cytoloc)   # this is the chr band
                            f.addSubsequenceOfFeature(g, loc)
                            f.addFeatureToGraph(g, True, None, is_gene)

                # end adding causative genes/features

            # check if moved, if so,
            # make it deprecated and
            # replaced consider class to the other thing(s)
            # some entries have been moved to multiple other entries and
            # use the joining raw word "and"
            # 612479 is movedto:  "603075 and 603029"  OR
            # others use a comma-delimited list, like:
            # 610402 is movedto: "609122,300870"
            if e['entry']['status'] == 'moved':
                if re.search(r'and', str(e['entry']['movedTo'])):
                    # split the movedTo entry on 'and'
                    newids = re.split(r'and', str(e['entry']['movedTo']))
                elif len(str(e['entry']['movedTo']).split(',')) > 0:
                    # split on the comma
                    newids = str(e['entry']['movedTo']).split(',')
                else:
                    # make a list of one
                    newids = [str(e['entry']['movedTo'])]
                # cleanup whitespace and add OMIM prefix to numeric portion
                fixedids = []
                for i in newids:
                    fixedids.append('OMIM:'+i.strip())

                gu.addDeprecatedClass(g, omimid, fixedids)

            self._get_phenotypicseries_parents(e['entry'], g)
            self._get_mappedids(e['entry'], g)
            self._get_mapped_gene_ids(e['entry'], g)

            self._get_pubs(e['entry'], g)

            self._get_process_allelic_variants(e['entry'], g)

        return


    def _process_morbidmap(self, limit):
        """
        This will process the morbidmap file to get the links between
        omim genes and diseases. Here, we create anonymous nodes for
        some variant loci that are variants of the gene that causes the disease.
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
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph
        line_counter = 0
        geno = Genotype(g)
        gu = GraphUtils(curie_map.get())
        assoc_count = 0
        with open('/'.join((self.rawdir, self.files['morbidmap']['file']))) as f:
            for line in f:
                line = line.strip()
                line_counter += 1
                (disorder, gene_symbols, gene_num, loc) = line.split('|')
                # TODO PYLINT loc unused
                # disorder = disorder label , number (mapping key)
                # 3-M syndrome 1, 273750 (3)|CUL7, 3M1|609577|6p21.1

                # but note that for those diseases where they are genomic loci
                # (not genes though), the omim id is only listed as the gene
                # Alopecia areata 1 (2)|AA1|104000|18p11.3-p11.2
                # when there's a gene and disease
                disorder_match = re.match(r'(.*), (\d{6})\s*(?:\((\d+)\))?',
                                          disorder)
                nogene_match = re.match(r'(.*)\s+\((\d+)\)', disorder)

                if disorder_match is not None:
                    disorder_parts = disorder_match.groups()
                    (disorder_label, disorder_num, phene_key) = disorder_parts

                    if self.testMode and (int(disorder_num) not in
                                          self.test_ids or
                                          int(gene_num) not in
                                          self.test_ids):
                        continue
                    assoc_count += 1
                    gene_symbols = gene_symbols.split(', ')
                    gene_id = 'OMIM:'+str(gene_num)
                    self._make_pheno_assoc(g, gene_id, gene_symbols[0],
                                           disorder_num, disorder_label,
                                           phene_key)
                elif nogene_match is not None:
                    # this is a case where the disorder a blended gene/phenotype
                    # we lookup the NCBIGene feature and make the association
                    (disorder_label, phene_key) = nogene_match.groups()
                    disorder_num = gene_num
                    # make what's in the gene column the disease
                    disorder_id = 'OMIM:'+str(disorder_num)
                    if self.testMode and int(disorder_num) not in self.test_ids:
                        continue
                    if disorder_id in self.omim_ncbigene_idmap:
                        # get the gene ids
                        gene_ids = self.omim_ncbigene_idmap[disorder_id]
                        if gene_ids is None:
                            continue
                        for gene_num in gene_ids:
                            # TODO add gene filter for testMode and NCBIGenes
                            gene_id = 'NCBIGene:'+str(gene_num).strip()
                            assoc_count += 1
                            self._make_pheno_assoc(g, gene_id, gene_symbols[0],
                                                   disorder_num, disorder_label,
                                                   phene_key)
                    else:
                        # we can create an anonymous feature to house this thing
                        # for example, 158900
                        feature_id = self._make_anonymous_feature(gene_num)
                        assoc_count += 1
                        self._make_pheno_assoc(g, feature_id, gene_symbols[0],
                                               disorder_num, disorder_label,
                                               phene_key)

                        logger.info("We don't have an NCBIGene feature id to link with %s, %s",
                                    disorder_id, disorder_label)

                    if self.testMode and int(gene_num) not in self.test_ids:
                        continue

                else:
                    logger.warning("There are misformatted row %d:%s",
                                   line_counter, str(line))

                if not self.testMode and limit is not None and line_counter > limit:
                    break

            gu.loadProperties(g, geno.object_properties, gu.OBJPROP)
            gu.loadProperties(g, G2PAssoc.object_properties, gu.OBJPROP)
            gu.loadProperties(g, G2PAssoc.annotation_properties, gu.ANNOTPROP)
            gu.loadProperties(g, G2PAssoc.datatype_properties, gu.DATAPROP)
            logger.info("Added %d G2P associations", assoc_count)

        return

    def _make_anonymous_feature(self, omim_num):

        feature_id = '_feature'+omim_num
        if self.nobnodes:
            feature_id = ':'+feature_id

        return feature_id

    def _make_pheno_assoc(self, g, gene_id, gene_symbol, disorder_num,
                          disorder_label, phene_key):

        geno = Genotype(g)
        disorder_id = ':'.join(('OMIM', disorder_num))
        rel_id = self.gu.object_properties['has_phenotype']  # default
        rel_label = 'causes'
        if re.match(r'\[', disorder_label):
            rel_id = self.gu.object_properties['is_marker_for']
            rel_label = 'is a marker for'
        elif re.match(r'\{', disorder_label):
            rel_id = self.gu.object_properties['contributes_to']
            rel_label = 'contributes to'
        elif re.match(r'\?', disorder_label):
            # this is a questionable mapping!  skip?
            rel_id = self.gu.object_properties['contributes_to']
            rel_label = 'contributes to'

        evidence = self._map_phene_mapping_code_to_eco(phene_key)

        # we actually want the association between the gene and the disease
        # to be via an alternate locus not the "wildtype" gene itself.
        # so we make an anonymous alternate locus,
        # and put that in the association.
        # but we only need to do that in the cases when it's not an NCBIGene
        # (as that is a sequence feature itself)
        if re.match(r'OMIM:', gene_id):
            alt_locus = '_'+re.sub(r':', '', gene_id)+'-'+disorder_num+'VL'
            alt_label = gene_symbol.strip()
            if alt_label is not None and alt_label != '':
                alt_label = ' '.join(('some variant of', alt_label,
                                      'that', rel_label, disorder_label))
            else:
                alt_label = None

            if self.nobnodes:
                alt_locus = ':'+alt_locus

            self.gu.addIndividualToGraph(g, alt_locus, alt_label,
                                         Genotype.genoparts['variant_locus'])
            geno.addAlleleOfGene(alt_locus, gene_id)
        else:
            # assume it's already been added
            alt_locus = gene_id

        assoc = G2PAssoc(self.name, alt_locus, disorder_id, rel_id)
        assoc.add_evidence(evidence)
        assoc.add_association_to_graph(g, self.nobnodes)

        return

    @staticmethod
    def _get_description(entry):
        """
        Get the description of the omim entity
        from the textSection called 'description'.
        Note that some of these descriptions have linebreaks.
        If printed in turtle syntax, they will appear to be triple-quoted.
        :param entry:
        :return:
        """
        d = None
        if entry is not None:
            if 'textSectionList' in entry:
                textSectionList = entry['textSectionList']
                for ts in textSectionList:
                    if ts['textSection']['textSectionName'] == 'description':
                        d = ts['textSection']['textSectionContent']
                        # there are internal references to OMIM identifiers in
                        # the description, I am formatting them in our style.
                        d = re.sub(r'{(\\d+)}', 'OMIM:\\1', d)

                        # TODO
                        # reformat the citations in the description with PMIDs
                        break

        return d

    def _get_process_allelic_variants(self, entry, g):
        gu = GraphUtils(curie_map.get())
        geno = Genotype(g)
        # du = DipperUtil() # TODO PYLINT unused du
        if entry is not None:
            # to hold the entry-specific publication mentions
            # for the allelic variants
            publist = {}
            entry_num = entry['mimNumber']

            # process the ref list just to get the pmids
            ref_to_pmid = self._get_pubs(entry, g)

            if 'allelicVariantList' in entry:
                allelicVariantList = entry['allelicVariantList']
                for al in allelicVariantList:
                    al_num = al['allelicVariant']['number']
                    al_id = 'OMIM:'+str(entry_num)+'.'+str(al_num).zfill(4)
                    al_label = None
                    al_description = None
                    if al['allelicVariant']['status'] == 'live':
                        publist[al_id] = set()
                        if 'mutations' in al['allelicVariant']:
                            al_label = al['allelicVariant']['mutations']
                        if 'text' in al['allelicVariant']:
                            al_description = al['allelicVariant']['text']
                            m = re.findall(r'\{(\d+)\:', al_description)
                            publist[al_id] = set(m)
                        geno.addAllele(al_id, al_label,
                                       geno.genoparts['variant_locus'],
                                       al_description)
                        geno.addAlleleOfGene(al_id, 'OMIM:'+str(entry_num),
                                             geno.object_properties['is_sequence_variant_instance_of'])
                        for r in publist[al_id]:
                            pmid = ref_to_pmid[int(r)]
                            gu.addTriple(g, pmid,
                                         gu.object_properties['is_about'],
                                         al_id)
                        # look up the pubmed id in the list of references
                        if 'dbSnps' in al['allelicVariant']:
                            dbsnp_ids = re.split(r',',
                                                 al['allelicVariant']['dbSnps'])
                            for dnum in dbsnp_ids:
                                did = 'dbSNP:'+dnum.strip()
                                gu.addIndividualToGraph(g, did, None)
                                gu.addSameIndividual(g, al_id, did)
                        if 'clinvarAccessions' in al['allelicVariant']:
                            # clinvarAccessions triple semicolon delimited
                            # each like RCV000020059;;;
                            rcv_ids = re.split(r';;;',
                                               al['allelicVariant']['clinvarAccessions'])
                            rcv_ids = [(re.match(r'(RCV\d+)\;\;', r)).group(1) for r in rcv_ids]
                            for rnum in rcv_ids:
                                rid = 'ClinVar:'+rnum
                                gu.addXref(g, al_id, rid)
                        gu.addPage(g, al_id,
                                   "http://omim.org/entry/"+
                                   str(entry_num)+"#"+
                                   str(al_num).zfill(4))
                    elif re.search(r'moved',
                                   al['allelicVariant']['status']):
                        # for both 'moved' and 'removed'
                        moved_ids = None
                        if 'movedTo' in al['allelicVariant']:
                            moved_id = 'OMIM:'+al['allelicVariant']['movedTo']
                            moved_ids = [moved_id]
                        gu.addDeprecatedIndividual(g, al_id, moved_ids)
                    else:
                        logger.error('Uncaught alleleic variant status %s',
                                     al['allelicVariant']['status'])
                # end loop allelicVariantList

        return

    @staticmethod
    def _map_phene_mapping_code_to_eco(code):
        # phenotype mapping code
        # 1 - the disorder is placed on the map based on its association with a
        #       gene, but the underlying defect is not known.
        # 2 - the disorder has been placed on the map by linkage;
        #       no mutation has been found.
        # 3 - the molecular basis for the disorder is known;
        #       a mutation has been found in the gene.
        # 4 - a contiguous gene deletion or duplication syndrome,
        #       multiple genes are deleted or duplicated causing the phenotype.
        eco_code = 'ECO:0000000'  # generic evidence
        phene_code_to_eco = {
            # inference from expert knowledge
            '1': 'ECO:0000306',
            # genomic context evidence
            '2': 'ECO:0000177',
            # sequencing assay evidence
            '3': 'ECO:0000220',
            # sequencing assay evidence
            '4': 'ECO:0000220'
        }

        if str(code) in phene_code_to_eco:
            eco_code = phene_code_to_eco.get(code)
        else:
            logger.error("unmapped phene code %s", code)

        return eco_code

    @staticmethod
    def _cleanup_label(label):
        """
        Reformat the ALL CAPS OMIM labels to something more pleasant to read.
        This will:
        1.  remove the abbreviation suffixes
        2.  convert the roman numerals to integer numbers
        3.  make the text title case,
            except for suplied conjunctions/prepositions/articles
        :param label:
        :return:
        """
        conjunctions = ['and', 'but', 'yet', 'for', 'nor', 'so']
        little_preps = ['at', 'by', 'in', 'of', 'on', 'to', 'up', 'as', 'it', 'or']
        articles = ['a', 'an', 'the']

        # remove the abbreviation
        l = re.split(r';', label)[0]

        fixedwords = []
        i = 0
        for w in l.split():
            i += 1
            # convert the roman numerals to numbers,
            # but assume that the first word is not
            # a roman numeral (this permits things like "X inactivation"
            if i > 1 and re.match(romanNumeralPattern, w):
                n = fromRoman(w)
                # make the assumption that the number of syndromes are <100
                # this allows me to retain "SYNDROME C"
                # and not convert it to "SYNDROME 100"
                if 0 < n < 100:
                    # get the non-roman suffix, if present.
                    # for example, IIIB or IVA
                    suffix = w.replace(toRoman(n), '', 1)
                    fixed = ''.join((str(n), suffix))
                    w = fixed

            # capitalize first letter
            w = w.title()

            # replace interior conjunctions, prepositions,
            # and articles with lowercase
            if w.lower() in (conjunctions+little_preps+articles) and i != 1:
                w = w.lower()

            fixedwords.append(w)

        l = ' '.join(fixedwords)
        # print (label,'-->',l)
        return l

    def _process_phenotypicseries(self, limit):
        """
        Creates classes from the OMIM phenotypic series list.
        These are grouping classes to hook the more granular OMIM diseases.
        :param limit:
        :return:
        """
        if self.testMode:
            g = self.testgraph
        else:
            g = self.graph
        logger.info("getting phenotypic series titles")
        gu = GraphUtils(curie_map.get())
        line_counter = 0
        start = False
        with open('/'.join((self.rawdir,
                            self.files['phenotypicSeries']['file']))) as f:
            for line in f:
                # there's several lines of header in the file,
                # so need to skip several lines:
                if not start:
                    if re.match(r'Phenotypic Series', line):
                        start = True
                    continue
                if re.match(r'\w*$', line):
                    # skip blank lines
                    continue
                line = line.strip()
                line_counter += 1
                (ps_label, ps_num) = line.split('\t')
                omim_id = 'OMIM:'+ps_num
                gu.addClassToGraph(g, omim_id, ps_label)

                if not self.testMode and limit is not None and line_counter > limit:
                    break

        return

    @staticmethod
    def _get_phenotypicseries_parents(entry, g):
        """
        Extract the phenotypic series parent relationship out of the entry
        :param entry:
        :return:
        """
        gu = GraphUtils(curie_map.get())
        omimid = 'OMIM:'+str(entry['mimNumber'])
        # the phenotypic series mappings
        serieslist = []
        if 'phenotypicSeriesExists' in entry:
            if entry['phenotypicSeriesExists'] is True:
                if 'phenotypeMapList' in entry:
                    phenolist = entry['phenotypeMapList']
                    for p in phenolist:
                        serieslist.append(p['phenotypeMap']['phenotypicSeriesNumber'])
                if 'geneMap' in entry and 'phenotypeMapList' in entry['geneMap']:
                    phenolist = entry['geneMap']['phenotypeMapList']
                    for p in phenolist:
                        if 'phenotypicSeriesNumber' in p['phenotypeMap']:
                            serieslist.append(p['phenotypeMap']['phenotypicSeriesNumber'])
        # add this entry as a subclass of the series entry
        for ser in serieslist:
            series_id = 'OMIM:'+ser
            gu.addClassToGraph(g, series_id, None)
            gu.addSubclass(g, series_id, omimid)

        return

    # TODO PYLINT Method could be a function
    def _get_mappedids(self, entry, g):
        """
        Extract the Orphanet and UMLS ids as equivalences from the entry
        :param entry:
        :return:
        """
        gu = GraphUtils(curie_map.get())
        omimid = 'OMIM:'+str(entry['mimNumber'])
        orpha_mappings = []
        if 'externalLinks' in entry:
            links = entry['externalLinks']
            if 'orphanetDiseases' in links:
                # triple semi-colon delimited list of
                # double semi-colon delimited orphanet ID/disease pairs
                # 2970;;566;;Prune belly syndrome
                items = links['orphanetDiseases'].split(';;;')
                for i in items:
                    # note 'internal_num unused
                    (orpha_num, internal_num, orpha_label) = i.split(';;')
                    orpha_id = 'Orphanet:'+orpha_num.strip()
                    orpha_mappings.append(orpha_id)
                    gu.addClassToGraph(g, orpha_id, orpha_label.strip())
                    gu.addXref(g, omimid, orpha_id)

            if 'umlsIDs' in links:
                umls_mappings = links['umlsIDs'].split(',')
                for i in umls_mappings:
                    umls_id = 'UMLS:'+i
                    gu.addClassToGraph(g, umls_id, None)
                    gu.addXref(g, omimid, umls_id)

        return

    def _get_mapped_gene_ids(self, entry, g):

        gene_ids = []
        gu = GraphUtils(curie_map.get())
        omimid = 'OMIM:'+str(entry['mimNumber'])
        if 'externalLinks' in entry:
            links = entry['externalLinks']
            omimtype = self._get_omimtype(entry)
            if 'geneIDs' in links:
                entrez_mappings = links['geneIDs']
                gene_ids = entrez_mappings.split(',')
                self.omim_ncbigene_idmap[omimid] = gene_ids
                if omimtype == Genotype.genoparts['gene']:
                    for i in gene_ids:
                        gu.addEquivalentClass(g, omimid, 'NCBIGene:'+str(i))

        return gene_ids

    def _get_alt_labels(self, titles):
        """
        From a string of delimited titles, make an array.
        This assumes that the titles are double-semicolon (';;') delimited.
        This will additionally pass each through the _cleanup_label method to
        convert the screaming ALL CAPS to something more pleasant to read.
        :param titles:
        :return: an array of cleaned-up labels
        """

        labels = []
        # "alternativeTitles": "ACROCEPHALOSYNDACTYLY, TYPE V; ACS5;;\nACS V;;\nNOACK SYNDROME",
        # "includedTitles": "CRANIOFACIAL-SKELETAL-DERMATOLOGIC DYSPLASIA, INCLUDED"

        for t in titles.split(';;'):
            # remove ', included', if present
            l = re.sub(r',\s*INCLUDED', '', t.strip(), re.IGNORECASE)
            l = self._cleanup_label(l)
            labels.append(l)

        return labels

    def _get_pubs(self, entry, g):
        """
        Extract mentioned publications from the reference list
        :param entry:
        :return:
        """

        ref_to_pmid = {}
        du = DipperUtil()
        entry_num = entry['mimNumber']
        gu = GraphUtils(curie_map.get())
        if 'referenceList' in entry:
            reflist = entry['referenceList']
            for r in reflist:
                if 'pubmedID' in r['reference']:
                    pub_id = 'PMID:' + str(r['reference']['pubmedID'])
                    ref = Reference(pub_id, Reference.ref_types['journal_article'])
                else:
                    # make blank node for internal reference
                    pub_id = '_OMIM' + str(entry_num) + 'ref' + str(r['reference']['referenceNumber'])
                    if self.nobnodes:
                        pub_id = ':' + pub_id
                    ref = Reference(pub_id)
                    title = author_list = source = citation = None
                    if 'title' in r['reference']:
                        title = r['reference']['title']
                        ref.setTitle(title)
                    if 'authors' in r['reference']:
                        author_list = r['reference']['authors']
                        ref.setAuthorList(author_list)
                        citation = re.split(r'\.\,', author_list)[0] + ' et al'
                    if 'source' in r['reference']:
                        source = r['reference']['source']
                    citation = '; '.join(du.flatten([citation, title, source]))
                    ref.setShortCitation(citation)
                ref.addRefToGraph(g)
                ref_to_pmid[r['reference']['referenceNumber']] = pub_id

                # add is_about for the pub
                omim_id = 'OMIM:'+str(entry_num)
                gu.addTriple(g,
                             omim_id, gu.object_properties['mentions'],
                             pub_id)

        return ref_to_pmid

    @staticmethod
    def _get_omimtype(entry):
        """
        Here, we look at the omim 'prefix' to help to type the entry.
        For now, we only classify omim entries as genes;
        the rest we leave alone.
        :param entry:
        :return:
        """

        # An asterisk (*) before an entry number indicates a gene.
        # A number symbol (#) before an entry number indicates
        # that it is a descriptive entry, usually of a phenotype,
        # and does not represent a unique locus.
        # The reason for the use of the number symbol
        # is given in the first paragraph of the entry.
        # Discussion of any gene(s) related to the phenotype resides in
        # another entry(ies) as described in the first paragraph.
        #
        # A plus sign (+) before an entry number indicates that the
        # entry contains the description of a gene of
        # known sequence and a phenotype.
        #
        # A percent sign (%) before an entry number indicates that the
        # entry describes a confirmed mendelian phenotype or phenotypic locus
        # for which the underlying molecular basis is not known.
        #
        # No symbol before an entry number generally indicates a
        # description of a phenotype for which the mendelian basis,
        # although suspected, has not been clearly established
        # or that the separateness of this phenotype
        # from that in another entry is unclear.
        #
        # A caret (^) before an entry number means the
        # entry no longer exists because it was removed from the database
        # or moved to another entry as indicated.
        prefix = None
        type_id = None
        if 'prefix' in entry:
            prefix = entry['prefix']

        if prefix == '*':
            # gene, may not have a known sequence or a phenotype
            # note that some genes are also phenotypes,
            # even in this class, like 102480
            # examples: 102560,102480,100678,102750
            type_id = Genotype.genoparts['gene']  # doublecheck this
        elif prefix == '#':
            # phenotype/disease -- indicate that here?
            # examples: 104200,105400,114480,115300,121900
            pass
        elif prefix == '+':
            # gene of known sequence and has a phenotype
            # examples: 107670,110600,126453
            type_id = Genotype.genoparts['gene']  # doublecheck this
        elif prefix == '%':
            # this is a disease (with a known locus).
            # examples include:  102150,104000,107200,100070
            type_id = Genotype.genoparts['heritable_phenotypic_marker']
        elif prefix == '':
            # this is probably just a phenotype
            pass

        return type_id

    def getTestSuite(self):
        import unittest
        # TODO PYLINT  Unable to import 'tests.test_omim'
        from tests.test_omim import OMIMTestCase

        test_suite = unittest.TestLoader().loadTestsFromTestCase(OMIMTestCase)

        return test_suite


def get_omim_id_from_entry(entry):
    if entry is not None and 'mimNumber' in entry:
        omimid = 'OMIM:'+str(entry['mimNumber'])
    else:
        omimid = None
    return omimid

def filter_keep_phenotype_entry_ids(entry, graph=None):
    # TODO PYLINT  Unused argument 'graph'
    omim_id = get_omim_id_from_entry(entry['entry'])
    # TODO PYLINT Access to a protected member _get_omimtype of a client class
    omim_type = OMIM._get_omimtype(entry['entry'])
    if omim_type != Genotype.genoparts['gene'] and omim_type != Genotype.genoparts['biological_region']:
        return omim_id

    return None

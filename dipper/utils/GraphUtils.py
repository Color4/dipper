import re
import logging
from rdflib import Literal, URIRef, BNode, Namespace, ConjunctiveGraph
from rdflib.namespace import DC, RDF, RDFS, OWL, XSD, FOAF

from dipper.utils.CurieUtil import CurieUtil

__author__ = 'nlw'

logger = logging.getLogger(__name__)


class GraphUtils:

    # FIXME - i've duplicated relationships in Assoc and here -
    #         pick one or the other and refactor
    # TODO -  refactor using the getNode() method to clear out the
    #         URIRef(cu.get_uri(<id>)) nonsense

    OWLCLASS = OWL['Class']
    OWLIND = OWL['NamedIndividual']
    OWLRESTRICTION = OWL['Restriction']
    OWLPROP = OWL['ObjectProperty']
    OBJPROP = OWL['ObjectProperty']
    ANNOTPROP = OWL['AnnotationProperty']
    DATAPROP = OWL['DatatypeProperty']
    SUBCLASS = RDFS['subClassOf']
    PERSON = FOAF['Person']

    annotation_properties = {
        'replaced_by': 'IAO:0100001',
        'consider': 'OIO:consider',
        'hasExactSynonym': 'OIO:hasExactSynonym',
        'hasRelatedSynonym': 'OIO:hasRelatedSynonym',
        'definition': 'IAO:0000115',
        'has_xref': 'OIO:hasDbXref',
        'clique_leader': 'MONARCH:cliqueLeader'
    }

    object_properties = {
        'has_disposition': 'GENO:0000208',
        'has_phenotype': 'RO:0002200',
        'in_taxon': 'RO:0002162',
        'has_quality': 'RO:0000086',
        'has_qualifier': 'GENO:0000580',
        'towards': 'RO:0002503',
        'has_subject': ':hasSubject',
        'has_object': ':hasObject',
        'has_predicate': ':hasPredicate',
        'is_about': 'IAO:0000136',
        'has_member': 'RO:0002351',
        'member_of': 'RO:0002350',
        'involved_in': 'RO:0002331',
        'enables': 'RO:0002327',
        'derives_from': 'RO:0001000',
        'part_of': 'BFO:0000050',
        'has_part': 'BFO:0000051',
        'mentions': 'IAO:0000142',
        'model_of': 'RO:0003301',
        'has_gene_product': 'RO:0002205',
        'existence_starts_at': 'UBERON:existence_starts_at',
        'existence_starts_during': 'RO:0002488',
        'existence_ends_at': 'UBERON:existence_ends_at',
        'existence_ends_during': 'RO:0002492',
        'starts_with': 'RO:0002224',
        'starts_during': 'RO:0002091',
        'ends_during': 'RO:0002093',
        'ends_with': 'RO:0002230',
        'occurs_in': 'BFO:0000066',
        'has_environment_qualifier': 'GENO:0000580',
        'has_begin_stage_qualifier': 'GENO:0000630',
        'has_end_stage_qualifier': 'GENO:0000631',
        'correlates_with': 'RO:0002610',
        'substance_that_treats': 'RO:0002606',
        'is_marker_for': 'RO:0002607',
        'contributes_to': 'RO:0002326',
        'has_origin': 'GENO:0000643',
        'has_author': 'ERO:0000232',
        'dc:source': 'dc:source',
        'dc:evidence': 'dc:evidence',
        'has_evidence': 'RO:0002558',
        'causally_upstream_of_or_within': 'RO:0002418',
        'causally influences': 'RO:0002566'
    }

    datatype_properties = {
        'position': 'faldo:position',
        'has_measurement': 'IAO:0000004',
    }

    properties = annotation_properties.copy()
    properties.update(object_properties)
    properties.update(datatype_properties)

    def __init__(self, curie_map, materialize_bnodes=False):
        self.curie_map = curie_map
        self.cu = CurieUtil(curie_map)         # TEC: what is cu really?
        self.nobnodes = materialize_bnodes

        return

    def addClassToGraph(self, g, id, label, type=None, description=None):
        """
        Any node added to the graph will get at least 3 triples:
        *(node, type, owl:Class) and
        *(node, label, literal(label))
        *if a type is added,
            then the node will be an OWL:subclassOf that the type
        *if a description is provided,
            it will also get added as a dc:description
        :param id:
        :param label:
        :param type:
        :param description:
        :return:

        """

        n = self.getNode(id)

        g.add((n, RDF['type'], self.OWLCLASS))
        if label is not None:
            g.add((n, RDFS['label'], Literal(label)))
        if type is not None:
            t = URIRef(self.cu.get_uri(type))
            g.add((n, self.SUBCLASS, t))
        if description is not None:
            g.add((n, DC['description'], Literal(description)))
        return g

    def addIndividualToGraph(self, g, id, label, type=None, description=None):
        n = self.getNode(id)

        if label is not None:
            g.add((n, RDFS['label'], Literal(label)))
        if type is not None:
            t = self.getNode(type)
            g.add((n, RDF['type'], t))
        else:
            g.add((n, RDF['type'], self.OWLIND))
        if description is not None:
            g.add((n, DC['description'], Literal(description)))
        return g

    def addOWLPropertyClassRestriction(
            self, g, class_id, property_id, property_value):

        # make a blank node to hold the property restrictions
        # scrub the colons, they will make the ttl parsers choke
        nid = \
            '_'+re.sub(r':', '', property_id)+re.sub(r':', '', property_value)
        n = self.getNode(nid)

        g.add((n, RDF['type'], self.OWLRESTRICTION))
        g.add((n, OWL['onProperty'], self.getNode(property_id)))
        g.add((n, OWL['someValuesFrom'], self.getNode(property_value)))

        g.add((self.getNode(class_id), self.SUBCLASS, n))

        return

    def addEquivalentClass(self, g, id1, id2):
        n1 = self.getNode(id1)
        n2 = self.getNode(id2)

        if n1 is not None and n2 is not None:
            g.add((n1, OWL['equivalentClass'], n2))

        return

    def addSameIndividual(self, g, id1, id2):
        n1 = self.getNode(id1)
        n2 = self.getNode(id2)

        if n1 is not None and n2 is not None:
            g.add((n1, OWL['sameAs'], n2))

        return

    def addPerson(self, graph, person_id, person_label):
        graph.add((self.getNode(person_id), RDF['type'], self.PERSON))
        if person_label is not None:
            graph.add(
                (self.getNode(person_id), RDFS['label'],
                 Literal(person_label)))
        return

    def addDeprecatedClass(self, g, oldid, newids=None):
        """
        Will mark the oldid as a deprecated class.
        if one newid is supplied, it will mark it as replaced by.
        if >1 newid is supplied, it will mark it with consider properties
        :param g:
        :param oldid: the class id to deprecate
        :param newids: the class idlist that is
                       the replacement(s) of the old class.  Not required.
        :return:

        """

        n1 = URIRef(self.cu.get_uri(oldid))
        g.add((n1, RDF['type'], self.OWLCLASS))

        self._addReplacementIds(g, oldid, newids)

        return

    def addDeprecatedIndividual(self, g, oldid, newids=None):
        """
        Will mark the oldid as a deprecated individual.
        if one newid is supplied, it will mark it as replaced by.
        if >1 newid is supplied, it will mark it with consider properties
        :param g:
        :param oldid: the individual id to deprecate
        :param newids: the individual idlist that is the replacement(s) of
                       the old individual.  Not required.
        :return:

        """

        n1 = URIRef(self.cu.get_uri(oldid))
        g.add((n1, RDF['type'], self.OWLIND))

        self._addReplacementIds(g, oldid, newids)

        return

    def _addReplacementIds(self, g, oldid, newids):
        consider = URIRef(self.cu.get_uri(self.properties['consider']))
        replaced_by = URIRef(self.cu.get_uri(self.properties['replaced_by']))

        n1 = URIRef(self.cu.get_uri(oldid))
        g.add((n1, OWL['deprecated'], Literal(True, datatype=XSD[bool])))

        if newids is not None:
            if len(newids) == 1:
                n = URIRef(self.cu.get_uri(newids[0]))
                g.add((n1, replaced_by, n))
            elif len(newids) > 0:
                for i in newids:
                    n = URIRef(self.cu.get_uri(i.strip()))
                    g.add((n1, consider, n))
        return

    def addSubclass(self, g, parentid, childid):
        p = URIRef(self.cu.get_uri(parentid))
        c = URIRef(self.cu.get_uri(childid))
        g.add((c, self.SUBCLASS, p))

        return

    def addType(self, graph, subject_id, type, type_is_literal=False):
        # FIXME check this... i don't think a type should ever be a literal
        if type_is_literal is True:
            graph.add((self.getNode(subject_id), RDF['type'], Literal(type)))
        else:
            graph.add(
                (self.getNode(subject_id), RDF['type'], self.getNode(type)))
        return

    def addLabel(self, graph, subject_id, label):
        graph.add(
            (self.getNode(subject_id), RDFS['label'], Literal(label)))
        return

    def addSynonym(self, g, cid, synonym, synonym_type=None):
        """
        Add the synonym as a property of the class cid.
        Assume it is an exact synonym, unless otherwise specified
        :param g:
        :param cid: class id
        :param synonym: the literal synonym label
        :param synonym_type: the CURIE of the synonym type (not the URI)
        :return:

        """
        n = self.getNode(cid)
        if n is None:
            logger.warning("GU.addSynonym() unable to anchor with %s", cid)
            return
        if synonym_type is None:
            # default
            synonym_type = URIRef(
                self.cu.get_uri(self.properties['hasExactSynonym']))
        else:
            synonym_type = URIRef(self.cu.get_uri(synonym_type))
        if synonym is not None:
            g.add((n, synonym_type, Literal(synonym)))
        else:
            logger.warning("GU.addSynonym() will not add a None for  %s", cid)
        return

    def addDefinition(self, g, cid, definition):
        if definition is not None:
            n = self.getNode(cid)
            p = URIRef(self.cu.get_uri(self.properties['definition']))
            g.add((n, p, Literal(definition)))

        return

    def addXref(self, g, cid, xrefid, xref_as_literal=False):
        self.addTriple(
            g, cid, self.properties['has_xref'], xrefid, xref_as_literal)
        return

    def addDepiction(self, g, subject_id, image_url):
        g.add(
            (self.getNode(subject_id), FOAF['depiction'], Literal(image_url)))
        return

    def addComment(self, g, subject_id, comment):
        g.add(
            (self.getNode(subject_id), DC['comment'],
             Literal(comment.strip())))
        return

    def addDescription(self, g, subject_id, description):
        g.add(
            (self.getNode(subject_id), DC['description'],
             Literal(description.strip())))
        return

    def addPage(self, g, subject_id, page_url):
        g.add(
            (self.getNode(subject_id), FOAF['page'], Literal(page_url)))
        return

    def addTitle(self, g, subject_id, title):
        g.add(
            (self.getNode(subject_id), DC['title'], Literal(title)))
        return

    def addMember(self, g, group_id, member_id):
        self.addTriple(
            g, group_id, self.properties['has_member'], member_id)

    def addMemberOf(self, g, member_id, group_id):
        self.addTriple(
            g, member_id, self.properties['member_of'], group_id)
        return

    def addInvolvedIn(self, g, member_id, group_id):
        self.addTriple(
            g, member_id, self.properties['involved_in'], group_id)

    def write(self, graph, fileformat=None, file=None):
        """
         a basic graph writer (to stdout) for any of the sources.
         this will write raw triples in rdfxml, unless specified.
         to write turtle, specify format='turtle'
         an optional file can be supplied instead of stdout
        :return: None

        """
        filewriter = None
        if fileformat is None:
            fileformat = 'rdfxml'
        if file is not None:
            filewriter = open(file, 'wb')

            logger.info("Writing triples in %s to %s", fileformat, file)
            graph.serialize(filewriter, format=fileformat)
            filewriter.close()
        else:
            print(graph.serialize(format=fileformat).decode())
        return

    def write_raw_triples(self, graph, file=None):
        """
         a basic graph writer (to stdout) for any of the sources.
         this will write raw triples in rdfxml, unless specified.
         to write turtle, specify format='turtle'
         an optional file can be supplied instead of stdout
        :return: None
        """
        filewriter = None
        if file is not None:
            filewriter = open(file, 'w')
            logger.info("Writing raw triples to %s", file)

        for (s, p, o) in graph:
            output = [s, p, o]

            print(' '.join(output), file=filewriter)

        if filewriter is not None:
            filewriter.close()

        return

    def write_compact_triples(self, graph, file=None):
        """
        Will write out the raw triples,
        except it will replace the full uri with the curie prefix
        :param graph:
        :param file:
        :return:
        """
        # TODO

        return

    def _getNode(self, curie, materialize_bnode):
        """
        This is a wrapper for creating a node with a given identifier.
        If an id starts with an underscore, it assigns it to a BNode, otherwise
        it creates it with a standard URIRef. Alternatively,
        if materialize_bnode is True,
        it will add any nodes that would have been blank into the BASE space.
        This will return None if it can't map the node properly.
        :param id:
        :return:
        """
        base = Namespace(self.curie_map.get(''))
        node = None
        if curie is not None and re.match(r'^_', curie):
            if materialize_bnode is True:
                node = base[curie]
            else:  # replace the leading underscore to make it cleaner
                node = BNode(re.sub(r'^_', '', curie, 1))
                # If theres also a colon
                node = BNode(re.sub(r'^:', '', node, 1))
        elif re.match(r'^\:', curie):  # do we need to remove embedded ID colons?
            node = base[re.sub(r':', '', curie, 1)]
        # Check if curie actually an IRI
        elif re.match(r'^http', curie):
            node = URIRef(curie)
        else:
            iri = self.cu.get_uri(curie)
            if iri is not None:
                node = URIRef(self.cu.get_uri(curie))
            else:
                logger.error("couldn't make URI for %s", curie)
        return node

    def getNode(self, id, materialize_bnode=False):

        return self._getNode(id, materialize_bnode)

    def addTriple(
            self, graph, subject_id, predicate_id, object_id,
            object_is_literal=False):

        if object_is_literal is True:
            graph.add(
                (self.getNode(subject_id), self.getNode(predicate_id),
                 Literal(object_id)))
        else:
            graph.add(
                (self.getNode(subject_id), self.getNode(predicate_id),
                 self.getNode(object_id)))
        return

    def loadObjectProperties(self, graph, op):
        """
        Given a graph, it will load the supplied object properties
        as owl['ObjectProperty'] types
        A convenience.
        Status: DEPRECATED.  See loadProperties().
        :param graph:
        :param op: a dictionary of object properties
        :return: None

        """
        self.loadProperties(graph, op, self.OBJPROP)
        return

    def loadProperties(self, graph, op, property_type):
        """
        DEPRECATED, commenting out until all references can
        be removed

        Given a graph, it will load the supplied object properties
        as the given property_type.
        :param graph: a graph
        :param op: a dictionary of object properties
        :param property_type: one of OWL:(Annotation|Data|Object)Property
        :return: None

        """

        #if property_type not in [self.OBJPROP, self.ANNOTPROP, self.DATAPROP]:
        #    logger.error(
        #        "bad property type assigned: %s, %s", property_type, op)
        #else:
        #    for k in op:
        #        graph.add(
        #            (self.getNode(op[k]), RDF['type'], property_type))
        return

    def loadAllProperties(self, graph):
        """
        A convenience to load all stored properties
        (object, data, and annotation) into the supplied graph.
        :param graph:
        :return:

        """

        self.loadProperties(graph, self.object_properties, self.OBJPROP)
        self.loadProperties(graph, self.annotation_properties, self.ANNOTPROP)
        self.loadProperties(graph, self.datatype_properties, self.DATAPROP)
        return

    def addOntologyDeclaration(self, graph, ontology_id):

        graph.add((self.getNode(ontology_id), RDF['type'], OWL['Ontology']))
        return

    def addOWLVersionIRI(self, graph, ontology_id, version_iri):
        graph.add(
            (self.getNode(ontology_id), OWL['versionIRI'],
             self.getNode(version_iri)))

        return

    def addOWLVersionInfo(self, graph, ontology_id, version_info):
        graph.add(
            (self.getNode(ontology_id), OWL['versionInfo'],
             Literal(version_info)))
        return

    def makeLeader(self, graph, node_id):
        """
        Add an annotation property to the given ```node_id```
        to be the clique_leader.
        This is a monarchism.
        :param graph:
        :param node_id:
        :return:
        """
        self.addTriple(
            graph, node_id, self.annotation_properties['clique_leader'],
            Literal(True, datatype=XSD[bool]), True)
        return

    @staticmethod
    def get_properties_from_graph(graph):
        """
        Wrapper for RDFLib.graph.predicates() that returns a unique set
        :param graph: RDFLib.graph
        :return: set, set of properties
        """
        # collapse to single list
        property_set = set()
        for row in graph.predicates():
            property_set.add(row)

        return property_set

    @staticmethod
    def add_property_axioms(graph, properties):
        ontology_graph = ConjunctiveGraph()

        ontologies = [
            'https://raw.githubusercontent.com/monarch-initiative/SEPIO-ontology/master/src/ontology/sepio.owl',
            'https://raw.githubusercontent.com/monarch-initiative/GENO-ontology/develop/src/ontology/geno.owl',
            'https://raw.githubusercontent.com/oborel/obo-relations/master/ro.owl',
            'http://purl.obolibrary.org/obo/iao.owl',
            'http://data.monarchinitiative.org/owl/ero.owl',
            'https://raw.githubusercontent.com/jamesmalone/OBAN/master/ontology/oban_core.ttl',
            'http://purl.obolibrary.org/obo/pco.owl',
            'http://purl.obolibrary.org/obo/xco.owl'
        ]

        for ontology in ontologies:
            logger.info("parsing: " + ontology)
            if re.search(r'\.owl', ontology):
                ontology_graph.parse(ontology, format='xml')
            elif re.search(r'\.ttl', ontology):
                ontology_graph.parse(ontology, format='turtle')
            else:
                ontology_graph.parse(ontology)

        # Get object properties
        graph = GraphUtils.add_property_to_graph(
            ontology_graph.subjects(RDF['type'], OWL['ObjectProperty']),
            graph, OWL['ObjectProperty'], properties)

        # Get annotation properties
        graph = GraphUtils.add_property_to_graph(
            ontology_graph.subjects(RDF['type'], OWL['AnnotationProperty']),
            graph, OWL['AnnotationProperty'], properties)

        # Get data properties
        graph = GraphUtils.add_property_to_graph(
            ontology_graph.subjects(RDF['type'], OWL['DatatypeProperty']),
            graph, OWL['DatatypeProperty'], properties)

        return graph

    @staticmethod
    def add_property_to_graph(results, graph, property_type, property_list):
        for row in results:
            if row in property_list:
                graph.add((row, RDF['type'], property_type))
        return graph

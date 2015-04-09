__author__ = 'nicole'

import re

from rdflib import Literal, URIRef, BNode, Namespace
from rdflib.namespace import DC, RDF, RDFS, OWL, XSD, FOAF

from dipper.utils.CurieUtil import CurieUtil


class GraphUtils:

    #FIXME - i've duplicated relationships in Assoc and here - pick one or the other and refactor
    #TODO refactor using the getNode() method to clear out the URIRef(cu.get_uri(<id>)) nonsense

    OWLCLASS=OWL['Class']
    OWLIND=OWL['NamedIndividual']
    OWLPROP=OWL['ObjectProperty']
    OBJPROP=OWL['ObjectProperty']
    ANNOTPROP=OWL['AnnotationProperty']
    DATAPROP=OWL['DataProperty']
    SUBCLASS=RDFS['subClassOf']
    PERSON=FOAF['person']


    annotation_properties = {
        'replaced_by' : 'IAO:0100001',
        'consider' : 'OIO:consider',
        'hasExactSynonym' : 'OIO:hasExactSynonym',
        'hasRelatedSynonym' : 'OIO:hasRelatedSynonym',
        'definition' : 'IAO:0000115',
        'has_xref' : 'OIO:hasDbXref',
    }

    object_properties = {
        'has_disposition':'GENO:0000208',
        'has_phenotype':'RO:0002200',
        'in_taxon' : 'RO:0002162',
        'has_quality' : 'RO:0000086',
        'towards' : 'RO:0002503',
        'has_subject' : ':hasSubject',
        'has_object' : ':hasObject',
        'has_predicate' : ':hasPredicate',
        'is_about' : 'IAO:00000136',
        'has_member': 'RO:0002351',
        'member_of': 'RO:0002350',
        'involved_in': 'RO:0002331',
        'derives_from': 'RO:0001000',
        'part_of': 'BFO:0000050',
        'mentions': 'IAO:0000142',
        'model_of' : 'ERO:0000233',
        'has_gene_product' : 'RO:0002205'
    }

    datatype_properties = {
        'position' : 'faldo:position',
        'has_measurement' : 'IAO:0000004',
        'environment' : 'GENO:0000099'
    }

    properties = annotation_properties.copy()
    properties.update(object_properties)
    properties.update(datatype_properties)



    def __init__(self,curie_map):
        self.curie_map = curie_map
        self.cu = CurieUtil(curie_map)
        return

    def addClassToGraph(self, g, id, label, type=None, description=None):

        '''
        Any node added to the graph will get at least 3 triples:
        *(node,type,owl:Class) and
        *(node,label,literal(label))
        *if a type is added, then the node will be an OWL:subclassOf that the type
        *if a description is provided, it will also get added as a dc:description
        :param id:
        :param label:
        :param type:
        :param description:
        :return:
        '''

        n = self._getNode(id)

        g.add((n, RDF['type'], self.OWLCLASS))
        if (label is not None):
            g.add((n, RDFS['label'], Literal(label)))
        if (type is not None):
            t = URIRef(self.cu.get_uri(type))
            g.add((n, self.SUBCLASS, t))
        if (description is not None):
            g.add((n, DC['description'], Literal(description)))
        return g

    def addIndividualToGraph(self, g, id, label, type=None, description=None):
        n = self._getNode(id)

        if (label is not None):
            g.add((n, RDFS['label'], Literal(label)))
        if (type is not None):
            t = URIRef(self.cu.get_uri(type))
            g.add((n, RDF['type'], t))
        else:
            g.add((n, RDF['type'], self.OWLIND))
        if (description is not None):
            g.add((n, DC['description'], Literal(description)))
        return g

    def addEquivalentClass(self,g,id1,id2):
        n1 = self._getNode(id1)
        n2 = self._getNode(id2)

        if (n1 is not None and n2 is not None):
            g.add((n1,OWL['equivalentClass'],n2))

        return

    def addSameIndividual(self,g,id1,id2):
        n1 = self._getNode(id1)
        n2 = self._getNode(id2)

        if (n1 is not None and n2 is not None):
            g.add((n1,OWL['sameAs'],n2))

        return

    def addPerson(self,graph,person_id,person_label):
        graph.add((self.getNode(person_id), RDF['type'], self.PERSON))
        if (person_label is not None):
            graph.add((self.getNode(person_id), RDFS['label'], Literal(person_label)))
        return


    def addDeprecatedClass(self,g,oldid,newids=None):
        '''
        Will mark the oldid as a deprecated class.
        if one newid is supplied, it will mark it as replaced by.
        if >1 newid is supplied, it will mark it with consider properties
        :param g:
        :param oldid: the class id to deprecate
        :param newids: the class idlist that is the replacement(s) of the old class.  Not required.
        :return:
        '''
        #print("INFO: adding deprecated class:",oldid, "with newids",newids)
        consider = URIRef(self.cu.get_uri(self.properties['consider']))
        replaced_by = URIRef(self.cu.get_uri(self.properties['replaced_by']))

        n1 = URIRef(self.cu.get_uri(oldid))
        g.add((n1,RDF['type'],self.OWLCLASS))
        g.add((n1,OWL['deprecated'],Literal(True,datatype=XSD[bool])))

        if (newids is not None):
            if (len(newids) == 1):
                n = URIRef(self.cu.get_uri(newids[0]))
                g.add((n1,replaced_by,n))
            elif (len(newids) > 0):
                for i in newids:
                    n = URIRef(self.cu.get_uri(i.strip()))
                    g.add((n1,consider,n))
        return

    def addSubclass(self,g,parentid,childid):
        p = URIRef(self.cu.get_uri(parentid))
        c = URIRef(self.cu.get_uri(childid))
        g.add((c,self.SUBCLASS,p))

        return

    def addType(self,graph,subject_id,type,type_is_literal=False):
        if type_is_literal is True:
            graph.add((self.getNode(subject_id), RDF['type'],Literal(type)))
        else:
            graph.add((self.getNode(subject_id), RDF['type'],self.getNode(type)))
        return

    def addLabel(self,graph,subject_id,label):
        graph.add((self.getNode(subject_id),RDFS['label'],Literal(label)))
        return

    def addSynonym(self,g,cid,synonym,synonym_type=None):
        '''
        Add the synonym as a property of the class cid.  Assume it is an exact synonym, unless
        otherwise specified
        :param g:
        :param cid: class id
        :param synonym: the literal synonym label
        :param synonym_type: the CURIE of the synonym type (not the URI)
        :return:
        '''
        n = self._getNode(cid)
        if (synonym_type is None):
            synonym_type = URIRef(self.cu.get_uri(self.properties['hasExactSynonym'])) #default
        else:
            synonym_type = URIRef(self.cu.get_uri(synonym_type))

        g.add((n, synonym_type, Literal(synonym)))
        return

    def addDefinition(self,g,cid,definition):
        if (definition is not None):
            n = self._getNode(cid)
            p = URIRef(self.cu.get_uri(self.properties['definition']))
            g.add((n,p,Literal(definition)))

        return

    def addXref(self,g,cid,xrefid):
        n1 = self._getNode(cid)
        n2 = self._getNode(xrefid)
        p = URIRef(self.cu.get_uri(self.properties['has_xref']))
        if (n1 is not None and n2 is not None):
            g.add((n1,p,n2))

        return

    def addDepiction(self,g,subject_id,image_url):
        g.add((self.getNode(subject_id),FOAF['depiction'],Literal(image_url)))
        return

    def addComment(self,g,subject_id,comment):
        g.add((self.getNode(subject_id),DC['comment'],Literal(comment.strip())))

        return

    def addDescription(self,g,subject_id,description):
        g.add((self.getNode(subject_id),DC['description'],Literal(description.strip())))
        return

    def addPage(self,g,subject_id,page_url):
        g.add((self.getNode(subject_id),FOAF['page'],Literal(page_url)))
        return

    def addMember(self, g, group_id, member_id):
        self.addTriple(g, group_id, self.properties['has_member'], member_id)

    def addMemberOf(self, g, member_id, group_id):
        self.addTriple(g, member_id, self.properties['member_of'], group_id)
        return

    def addInvolvedIn(self, g, member_id, group_id):
        self.addTriple(g, member_id, self.properties['involved_in'], group_id)

    def write(self, graph, format=None, file=None):
        """
         a basic graph writer (to stdout) for any of the sources.  this will write
         raw triples in rdfxml, unless specified.
         to write turtle, specify format='turtle'
         an optional file can be supplied instead of stdout
        :return: None
        """
        if (format is None):
            format = 'rdfxml'
        if (file is not None):
            filewriter = open(file, 'w')
            print("INFO: Writing triples in",format,"to",file)
            print(graph.serialize(format=format).decode(), file=filewriter)
            filewriter.close()
        else:
            print(graph.serialize(format=format).decode())
        return


    def _getNode(self,id):
        """
        This is a wrapper for creating a node with a given identifier.  If an id starts with an
        underscore, it assigns it to a BNode, otherwise it creates it with a standard URIRef.
        This will return None if it can't map the node properly.
        :param id:
        :return:
        """
        base=Namespace(self.curie_map.get(''))
        n=None
        if (id is not None and re.match('^_',id)):
            n = BNode(re.sub('_','',id,1))  #replace the leading underscore to make it cleaner
        elif (re.match('^\:',id)):
            n = base[re.sub(':','',id,1)]   #do we need to remove embedded colons in the ids?
        else:
            u = self.cu.get_uri(id)
            if (u is not None):
                n = URIRef(self.cu.get_uri(id))
            else:
                print("ERROR: couldn't make URI for ",id)
        return n

    def getNode(self,id):

        return self._getNode(id)

    def addTriple(self,graph,subject_id,predicate_id,object,object_is_literal=False):
        if object_is_literal is True:
            graph.add((self.getNode(subject_id),self.getNode(predicate_id),Literal(object)))
        else:
            graph.add((self.getNode(subject_id),self.getNode(predicate_id),self.getNode(object)))

        return

    def loadObjectProperties(self,graph,op):
        """
        Given a graph, it will load the supplied object properties
        as owl['ObjectProperty'] types
        A convenience.
        Status: DEPRECATED.  See loadProperties().
        :param g: a graph
        :param op: a dictionary of object properties
        :return: None
        """
        self.loadProperties(graph,op,self.OBJPROP)

        return

    def loadProperties(self,graph,op,property_type):
        """
        Given a graph, it will load the supplied object properties
        as the given property_type.
        :param g: a graph
        :param op: a dictionary of object properties
        :param property_type: one of OWL:(Annotation|Data|Object)Property
        :return: None
        """

        if property_type not in [self.OBJPROP,self.ANNOTPROP,self.DATAPROP]:
            print("ERROR: bad property type assigned:",property_type)
        else:
            for k in op:
                graph.add((self.getNode(op[k]),RDF['type'],property_type))

        return

    def loadAllProperties(self,graph):
        """
        A convenience to load all stored properties (object, data, and annotation) into the supplied graph.
        :param graph:
        :return:
        """

        self.loadProperties(graph,self.object_properties,self.OBJPROP)
        self.loadProperties(graph,self.annotation_properties,self.ANNOTPROP)
        self.loadProperties(graph,self.datatype_properties,self.DATAPROP)

        return
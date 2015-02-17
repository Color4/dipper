from rdflib import Graph
import os
import hashlib
import urllib
from stat import *


class TestUtils:

    def __init__(self, source=None):
        # instantiate source object
        self.source = source
        self.graph = Graph()
        if (source is not None):
            self.source.load_bindings()

        return

    def query_graph(self, query):
        query_result = self.graph.query(query)

        for row in query_result:
            print(row)

        return

    def check_query_syntax(self, query):
        self.source.graph.query(query)
        return

    def load_graph_from_turtle(self):
        file = self.source.outdir+'/'+self.source.name+'.ttl'
        if not os.path.exists(file):
            raise Exception("file:"+file+" does not exist")
        # load turtle file into graph
        self.graph.parse(file, format="turtle")

        return

    def get_file_md5(self, directory, file, blocksize=2**20):
        # reference: http://stackoverflow.com/questions/
        #            1131220/get-md5-hash-of-big-files-in-python

        md5 = hashlib.md5()
        with open(os.path.join(directory, file), "rb") as f:
            while True:
                buffer = f.read(blocksize)
                if not buffer:
                    break
                md5.update(buffer)

        return md5.hexdigest()

    def get_remote_content_len(self, remote):
        """
        :param remote:
        :return: size of remote file
        """
        remote_file = urllib.request.urlopen(remote)
        byte_size = remote_file.info()['Content-Length']
        return byte_size

    def get_local_file_size(self, localfile):
        """
        :param localfile:
        :return: size of file
        """
        byte_size = os.stat(localfile)
        return byte_size[ST_SIZE]

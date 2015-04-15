#!/usr/bin/env python3

from dipper import curie_map
from rdflib import Graph

import unittest
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class GeneralGraphTestCase(unittest.TestCase):

    def setUp(self):
        self.graph = Graph()
        self.curie_map = curie_map.get()

    def tearDown(self):
        self.graph = None

    def test_curieprefixes(self):
        """
        This will ensure that we can create identifiers for all of the defined curie prefixes using the
        GraphUtils.getNode() method
        :return:
        """
        from dipper.utils.GraphUtils import GraphUtils

        gu = GraphUtils(self.curie_map)

        # add one id per curie as classes to the graph
        for p in self.curie_map.keys():
            testid = p+':testme'
            n = gu.getNode(testid)
            m = "prefix \""+p+"\" has an error...can't create graph node"
            self.assertTrue(n is not None, m)

        return

    def readGraphFromTurtleFile(self, f):
        """
        This will read the specified file into a graph.  A simple parsing test.
        :param f:
        :return:
        """
        import os
        vg = Graph()
        p = os.path.abspath(f)
        vg.parse(f, format="turtle")
        logger.info('Found %s graph nodes in %s', len(vg), p)
        self.assertTrue(len(vg) > 0, "No nodes found in "+p)

        return

    def readGraphIntoOWL(self, f):
        """
        test if the ttl can be parsed by owlparser
        this expects owltools to be accessible from commandline
        :param f: file of ttl
        :return:
        """

        import subprocess
        from subprocess import check_call

        status = check_call(["owltools", f], stderr=subprocess.STDOUT)
        # returns zero is success!
        if status != 0:
            logger.error('finished verifying with owltools with status %s', status)
        self.assertTrue(status == 0)

        return

if __name__ == '__main__':
    unittest.main()

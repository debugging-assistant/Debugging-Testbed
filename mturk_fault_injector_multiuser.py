import sys
import os
from datetime import datetime
# Mininet Imports
from mininet.topo import Topo
from mininet.node import Docker, Node
from mininet.net import Containernet
from mininet.nodelib import NAT
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.util import dumpNetConnections

# P4 Imports (files in same directory)
from p4_mininet import P4Switch, P4Host

import argparse
import subprocess
from time import sleep
import json
import fileinput
from socket import *
import random
import requests
import signal

parser = argparse.ArgumentParser(description='Distributed Reddit Setup to inject faults and debug with marple queries')
parser.add_argument('--behavioral-exe', help='Path to behavioral executable',
					type=str, action="store", required=False,
					default="~/behavioral-model/targets/simple_switch/simple_switch")
parser.add_argument('--thrift-port', help='Thrift server port for table updates',
					type=int, action="store", default=9090)
parser.add_argument('--mode', choices=['experiment', 'debug'], type=str, default='debug')
parser.add_argument('--json', help='Path to JSON config file',
					type=str, action="store", required=True)
parser.add_argument('--pcap-dump', help='Dump packets on interfaces to pcap files',
					type=str, action="store", required=False, default=False)
parser.add_argument('--ip', help='IP of the jaeger tracing collector', type=str, action="store", required=True)
parser.add_argument('--faults',help='Non-empty list of faults which are to be injected',type=int, nargs='+', action="store", required=True)
parser.add_argument('--port', help='HTTP forwarding port on the machine', type=int, action="store", required=True)
parser.add_argument('--app-choice', help='Choose between Reddit or Sockshop to be setup', type=str, action="store", required=True)
parser.add_argument('--domain',help='Domain name of the server', type=str, action="store", required=True)
args = parser.parse_args()

os.system('sudo mn -c')
serverSocket = socket(AF_INET, SOCK_STREAM)
serverAddress = ('0.0.0.0',30000)
serverSocket.bind(serverAddress)

current_fault = -1
current_app = ""
net = ""

class DemoSwitch(P4Switch):
	""" Demo switch that can hot-swap one query JSON for another. """
	def __init__(self, 
				 name, 
				 sw_path = None, 
				 json_path = None, 
				 thrift_port = None, 
				 pcap_dump = None, 
				 **kwargs):
		P4Switch.__init__(self, name,
						  sw_path = sw_path,
						  json_path = json_path,
						  thrift_port = thrift_port,
						  pcap_dump = pcap_dump,
						  **kwargs)

	def restart(self, json_path):
		"""Restart a new P4 switch with the new JSON"""
		print "Stopping P4 switch", self.name
		""" Execute part of the stop() routine. """
		self.output.flush()
		self.cmd('kill %' + self.sw_path)
		self.cmd('wait')
		""" Now re-run part of the start() routine that constructs a new switch
		path with the new JSON argument. """
		self.json_path = json_path
		args = [self.sw_path]
		# args.extend( ['--name', self.name] )
		# args.extend( ['--dpid', self.dpid] )
		for port, intf in self.intfs.items():
			if not intf.IP():
				args.extend( ['-i', str(port) + "@" + intf.name] )
		if self.pcap_dump:
			args.append("--pcap")
			# args.append("--useFiles")
		if self.thrift_port:
			args.extend( ['--thrift-port', str(self.thrift_port)] )
		if self.nanomsg:
			args.extend( ['--nanolog', self.nanomsg] )
		args.extend( ['--device-id', str(self.device_id)] )
		# P4Switch.device_id += 1
		args.append(self.json_path)
		if self.enable_debugger:
			args.append("--debugger")
		logfile = '/tmp/p4s.%s.log' % self.name
		print ' '.join(args)

		self.cmd( ' '.join(args) + ' >' + logfile + ' 2>&1 &' )
		# self.cmd( ' '.join(args) + ' > /dev/null 2>&1 &' )

		print "switch has been restarted"

class LinuxRouter( Node ):
	"Linux Router (a node with ip forwarding enabled) used to create iptable rules"

	def config( self,**params):
		super( LinuxRouter, self).config( **params )
		# Enable forwarding on the router
		self.cmd( 'sysctl net.ipv4.ip_forward=1' )

	def terminate( self ):
		self.cmd('sysctl net.ipv4.ipforward=0')
		super( LinuxRouter, self ).terminate()

class RedditTopo( Topo ):
	"Reddit distributed setup topology."

	def __init__( self, sw_path, json_path, pcap_dump, **opts ):
		"Create custom topo."

		# Initialize topology
		Topo.__init__( self, **opts )

		# Initialize linux router
		defaultIP = '10.0.0.10/24' # IP address for r0-eth1
		router = self.addNode('r0',cls=LinuxRouter, ip=defaultIP)

		# Add hosts and switches
		redditHost = self.addHost( 'h1', ip='10.0.0.2/24',mac = "00:04:00:00:00:00", cls=Docker, dimage = "pdawg/reddit_setup_with_opentracing_3steps:latest", dcmd="/sbin/init --startup-event=failsafe-boot", cpuset_cpus = '2,3,4,5' )
		firstHost = self.addHost( 'h2', ip='10.0.1.2/24',mac = "00:04:00:00:00:01", cls=Docker, dimage = "pdawg/cassandra_3users:latest", dcmd="/sbin/init --startup-event=failsafe-boot", cpuset_cpus = '8' )
		redditSwitch = self.addSwitch( 's3', sw_path=sw_path, json_path=json_path, thrift_port=9090, pcap_dump=pcap_dump)
		cassandraSwitch = self.addSwitch( 's4', sw_path=sw_path, json_path=json_path, thrift_port=9091, pcap_dump=pcap_dump )
		memcacheSwitch = self.addSwitch( 's5', sw_path=sw_path, json_path=json_path, thrift_port=9092, pcap_dump=pcap_dump )
		mcrouterSwitch = self.addSwitch( 's6', sw_path=sw_path, json_path=json_path, thrift_port=9093, pcap_dump=pcap_dump )
		postgresSwitch = self.addSwitch( 's7', sw_path=sw_path, json_path=json_path, thrift_port=9094, pcap_dump=pcap_dump )
		secondHost = self.addHost('h8', ip='10.0.2.2/24',mac = "00:04:00:00:00:02", cls=Docker, dimage = "pdawg/reddit_setup_memcache:latest", dcmd="/sbin/init --startup-event=failsafe-boot", cpuset_cpus = '9' )
		thirdHost = self.addHost('h9', ip='10.0.3.2/24',mac = "00:04:00:00:00:03", cls=Docker, dimage = "pdawg/reddit_setup_mcrouter:latest", dcmd="/sbin/init --startup-event=failsafe-boot", cpuset_cpus = '10' )
		fourthHost = self.addHost('h10', ip='10.0.4.2/24',mac = "00:04:00:00:00:04", cls=Docker, dimage = "pdawg/postgres_3users:latest", dcmd="/sbin/init --startup-event=failsafe-boot", cpuset_cpus = '6,5' )
	
		# Hosts and switches for creating congestion at various components of the system.
		redditfileclient = self.addHost('h11', ip='10.0.10.244/24',mac = "00:04:00:00:00:10", cls=P4Host )
		redditfileserver = self.addHost('h12', ip='10.0.11.245/24',mac = "00:04:00:00:00:11", cls=P4Host )
		redditcongestionSwitch = self.addSwitch( 's13', sw_path=sw_path, json_path=json_path, thrift_port=10090, pcap_dump=pcap_dump )
		cassandrafileclient = self.addHost('h14', ip='10.0.12.244/24',mac = "00:04:00:00:01:10", cls=P4Host )
		cassandrafileserver = self.addHost('h15', ip='10.0.13.245/24',mac = "00:04:00:00:01:11", cls=P4Host ) 
		cassandracongestionSwitch = self.addSwitch( 's16', sw_path=sw_path, json_path=json_path, thrift_port=10091, pcap_dump=pcap_dump )
		memcachefileclient = self.addHost('h17', ip='10.0.14.244/24',mac = "00:04:00:00:02:10", cls=P4Host )
		memcachefileserver = self.addHost('h18', ip='10.0.15.245/24',mac = "00:04:00:00:02:11", cls=P4Host )
		memcachecongestionSwitch = self.addSwitch( 's19', sw_path=sw_path, json_path=json_path, thrift_port=10092, pcap_dump=pcap_dump )
		mcrouterfileclient = self.addHost('h20', ip='10.0.16.244/24',mac = "00:04:00:00:03:10", cls=P4Host )
		mcrouterfileserver = self.addHost('h21', ip='10.0.17.245/24',mac = "00:04:00:00:03:11", cls=P4Host )
		mcroutercongestionSwitch = self.addSwitch( 's22', sw_path=sw_path, json_path=json_path, thrift_port=10093, pcap_dump=pcap_dump )
		postgresfileclient = self.addHost('h23', ip='10.0.18.244/24',mac = "00:04:00:00:04:10", cls=P4Host )
		postgresfileserver = self.addHost('h24', ip='10.0.19.245/24',mac = "00:04:00:00:04:11", cls=P4Host )
		postgrescongestionSwitch = self.addSwitch( 's25', sw_path=sw_path, json_path=json_path, thrift_port=10094, pcap_dump=pcap_dump )
		
		# Host to load webpages from reddit
		testHost = self.addHost('h26', ip='10.0.5.2/24',mac = "00:04:00:00:00:05" )

		# Hosts holding different dbs, caches, mq brokers, geo ip services
		rabbitHost = self.addHost('h27', ip='10.0.20.2/24',mac = "00:04:00:00:00:20", cls=Docker, dimage = "pdawg/reddit_setup_rabbit:latest", dcmd="/sbin/init --startup-event=failsafe-boot", cpuset_cpus = '7' )
		
		rabbitSwitch = self.addSwitch( 's80', sw_path=sw_path, json_path=json_path, thrift_port=9095, pcap_dump=pcap_dump )

		rabbitfileclient = self.addHost('h41', ip='10.0.40.244/24',mac = "00:04:00:00:20:10", cls=P4Host )
		rabbitfileserver = self.addHost('h42', ip='10.0.41.245/24',mac = "00:04:00:00:20:11", cls=P4Host )
		rabbitcongestionSwitch = self.addSwitch( 's43', sw_path=sw_path, json_path=json_path, thrift_port=10095, pcap_dump=pcap_dump )

		# Add links
		self.addLink( redditHost, redditSwitch )
		self.addLink( redditfileclient, redditSwitch )
		self.addLink( firstHost, cassandraSwitch )
		self.addLink( cassandrafileclient, cassandraSwitch )
		self.addLink( secondHost, memcacheSwitch )
		self.addLink( memcachefileclient, memcacheSwitch )
		self.addLink( thirdHost, mcrouterSwitch )
		self.addLink( mcrouterfileclient, mcrouterSwitch )
		self.addLink( fourthHost, postgresSwitch )
		self.addLink( postgresfileclient, postgresSwitch )
		self.addLink( rabbitHost, rabbitSwitch )
		self.addLink( rabbitfileclient, rabbitSwitch )

		# Add links for congestion
		self.addLink( redditSwitch, redditcongestionSwitch )
		self.addLink( redditfileserver, redditcongestionSwitch )
		self.addLink( cassandraSwitch, cassandracongestionSwitch )
		self.addLink( cassandrafileserver, cassandracongestionSwitch )
		self.addLink( memcacheSwitch, memcachecongestionSwitch )
		self.addLink( memcachefileserver, memcachecongestionSwitch ) 
		self.addLink( mcrouterSwitch, mcroutercongestionSwitch )
		self.addLink( mcrouterfileserver, mcroutercongestionSwitch )
		self.addLink( postgresSwitch, postgrescongestionSwitch )
		self.addLink( postgresfileserver, postgrescongestionSwitch )
		self.addLink( rabbitSwitch, rabbitcongestionSwitch )
		self.addLink( rabbitfileserver, rabbitcongestionSwitch )
		
	
		# Add links between the linux router and switches
		self.addLink( redditcongestionSwitch, router, intfName2='r0-eth1', addr2='00:aa:bb:cc:00:00', params2={'ip': defaultIP} )
		self.addLink( cassandracongestionSwitch, router, intfName2='r0-eth2', addr2='00:aa:bb:cc:00:01', params2={'ip': '10.0.1.10/24'} )
		self.addLink( memcachecongestionSwitch, router, intfName2='r0-eth3', addr2='00:aa:bb:cc:00:02', params2={'ip': '10.0.2.10/24'} )
		self.addLink( mcroutercongestionSwitch, router, intfName2='r0-eth4', addr2='00:aa:bb:cc:00:03', params2={'ip': '10.0.3.10/24'} )
		self.addLink( postgrescongestionSwitch, router, intfName2='r0-eth5', addr2='00:aa:bb:cc:00:04', params2={'ip': '10.0.4.10/24'} )
		self.addLink( testHost, router, intfName2='r0-eth6', addr2='00:aa:bb:cc:00:05', params2={'ip': '10.0.5.1/24'} )
		self.addLink( rabbitcongestionSwitch, router, intfName2='r0-eth7', addr2='00:aa:bb:cc:00:20', params2={'ip': '10.0.20.10/24'} )

class SockshopTopo( Topo ):
	"Sockshop distributed setup topology."

	def __init__( self, sw_path, json_path, pcap_dump, **opts ):
		"Create custom topo."

		# Initialize topology
		Topo.__init__( self, **opts )

		# Initialize linux router
		defaultIP = '10.0.0.10/24' # IP address for r0-eth1
		router = self.addNode('r0',cls=LinuxRouter, ip=defaultIP)

		hosts = []
		switches = []
		congestionswitches = []
		clients = []
		servers = []

		# Add hosts
		edgerouterHost = self.addHost( 'h1', ip='10.0.0.2/24',mac = "00:04:00:00:00:00", cls=Docker, dimage = "pdawg/weaveworksdemos-edge-router:latest", cpuset_cpus = '1')
		frontendHost = self.addHost( 'h2', ip='10.0.1.2/24',mac = "00:04:00:00:00:01", cls=Docker, dimage = "pdawg/weaveworksdemos-front-end:latest", cpuset_cpus = '2' )
		catalogueHost = self.addHost( 'h3', ip='10.0.2.2/24',mac = "00:04:00:00:00:02", cls=Docker, dimage = "pdawg/weaveworksdemos-catalogue:latest", cpuset_cpus = '3' )
		cataloguedbHost = self.addHost( 'h4', ip='10.0.3.2/24',mac = "00:04:00:00:00:03", cls=Docker, dimage = "pdawg/weaveworksdemos-catalogue-db:latest", cpuset_cpus = '4' )
		cartsHost = self.addHost( 'h5', ip='10.0.4.2/24',mac = "00:04:00:00:00:04", cls=Docker, dimage = "pdawg/weaveworksdemos-carts:latest", cpuset_cpus = '5' )
		cartsdbHost = self.addHost( 'h6', ip='10.0.5.2/24',mac = "00:04:00:00:00:05", cls=Docker, dimage = "pdawg/weaveworksdemos-mongodb:latest", cpuset_cpus = '6' )
		ordersHost = self.addHost( 'h7', ip='10.0.6.2/24',mac = "00:04:00:00:00:06", cls=Docker, dimage = "pdawg/weaveworksdemos-orders:latest", cpuset_cpus = '7' )
		ordersdbHost = self.addHost( 'h8', ip='10.0.7.2/24',mac = "00:04:00:00:00:07", cls=Docker, dimage = "pdawg/weaveworksdemos-mongodb:latest", cpuset_cpus = '8' )
		shippingHost = self.addHost( 'h9', ip='10.0.8.2/24',mac = "00:04:00:00:00:08", cls=Docker, dimage = "pdawg/weaveworksdemos-shipping:latest", cpuset_cpus = '9' )
		queuemasterHost = self.addHost( 'h10', ip='10.0.9.2/24',mac = "00:04:00:00:00:09", cls=Docker, dimage = "pdawg/weaveworksdemos-queue-master:latest", cpuset_cpus = '10', volumes=["/var/run/docker.sock:/var/run/docker.sock:rw"] )
		rabbitmqHost = self.addHost( 'h11', ip='10.0.10.2/24',mac = "00:04:00:00:00:0a", cls=Docker, dimage = "pdawg/weaveworksdemos-rabbitmq:latest", cpuset_cpus = '11' )
		paymentHost = self.addHost( 'h12', ip='10.0.11.2/24',mac = "00:04:00:00:00:0b", cls=Docker, dimage = "pdawg/weaveworksdemos-payment:latest", cpuset_cpus = '12' )
		userHost = self.addHost( 'h13', ip='10.0.12.2/24',mac = "00:04:00:00:00:0c", cls=Docker, dimage = "pdawg/weaveworksdemos-user:latest", cpuset_cpus = '13' )
		userdbHost = self.addHost( 'h14', ip='10.0.13.2/24',mac = "00:04:00:00:00:0d", cls=Docker, dimage = "pdawg/weaveworksdemos-user-db:latest", cpuset_cpus = '14' )
		usersimulatorHost = self.addHost( 'h15', ip='10.0.14.2/24',mac = "00:04:00:00:00:0e", cls=Docker, dimage = "pdawg/weaveworksdemos-load-test:latest", cpuset_cpus = '15' )
		hosts = [edgerouterHost, frontendHost, catalogueHost, cataloguedbHost, cartsHost, cartsdbHost, ordersHost, ordersdbHost, shippingHost, queuemasterHost, rabbitmqHost, paymentHost, userHost, userdbHost, usersimulatorHost]

		# Add switches
		edgerouterSwitch = self.addSwitch( 's16', sw_path=sw_path, json_path=json_path, thrift_port=9090, pcap_dump=pcap_dump )
		frontendSwitch = self.addSwitch( 's17', sw_path=sw_path, json_path=json_path, thrift_port=9091, pcap_dump=pcap_dump )
		catalogueSwitch = self.addSwitch( 's18', sw_path=sw_path, json_path=json_path, thrift_port=9092, pcap_dump=pcap_dump )
		cataloguedbSwitch = self.addSwitch( 's19', sw_path=sw_path, json_path=json_path, thrift_port=9093, pcap_dump=pcap_dump )
		cartsSwitch = self.addSwitch( 's20', sw_path=sw_path, json_path=json_path, thrift_port=9094, pcap_dump=pcap_dump )
		cartsdbSwitch = self.addSwitch( 's21', sw_path=sw_path, json_path=json_path, thrift_port=9095, pcap_dump=pcap_dump )
		ordersSwitch = self.addSwitch( 's22', sw_path=sw_path, json_path=json_path, thrift_port=9096, pcap_dump=pcap_dump )
		ordersdbSwitch = self.addSwitch( 's23', sw_path=sw_path, json_path=json_path, thrift_port=9097, pcap_dump=pcap_dump )
		shippingSwitch = self.addSwitch( 's24', sw_path=sw_path, json_path=json_path, thrift_port=9098, pcap_dump=pcap_dump )
		queuemasterSwitch = self.addSwitch( 's25', sw_path=sw_path, json_path=json_path, thrift_port=9099, pcap_dump=pcap_dump )
		rabbitmqSwitch = self.addSwitch( 's26', sw_path=sw_path, json_path=json_path, thrift_port=9100, pcap_dump=pcap_dump )
		paymentSwitch = self.addSwitch( 's27', sw_path=sw_path, json_path=json_path, thrift_port=9101, pcap_dump=pcap_dump )
		userSwitch = self.addSwitch( 's28', sw_path=sw_path, json_path=json_path, thrift_port=9102, pcap_dump=pcap_dump )
		userdbSwitch = self.addSwitch( 's29', sw_path=sw_path, json_path=json_path, thrift_port=9103, pcap_dump=pcap_dump ) 
		usersimulatorSwitch = self.addSwitch( 's30', sw_path=sw_path, json_path=json_path, thrift_port=9104, pcap_dump=pcap_dump ) 
		switches = [edgerouterSwitch, frontendSwitch, catalogueSwitch, cataloguedbSwitch, cartsSwitch, cartsdbSwitch, ordersSwitch, ordersdbSwitch, shippingSwitch, queuemasterSwitch, rabbitmqSwitch, paymentSwitch, userSwitch, userdbSwitch, usersimulatorSwitch]

		edgeroutercongestionSwitch = self.addSwitch( 's31', sw_path=sw_path, json_path=json_path, thrift_port=10090, pcap_dump=pcap_dump )
		frontendcongestionSwitch = self.addSwitch( 's32', sw_path=sw_path, json_path=json_path, thrift_port=10091, pcap_dump=pcap_dump )
		cataloguecongestionSwitch = self.addSwitch( 's33', sw_path=sw_path, json_path=json_path, thrift_port=10092, pcap_dump=pcap_dump )
		cataloguedbcongestionSwitch = self.addSwitch( 's34', sw_path=sw_path, json_path=json_path, thrift_port=10093, pcap_dump=pcap_dump )
		cartscongestionSwitch = self.addSwitch( 's35', sw_path=sw_path, json_path=json_path, thrift_port=10094, pcap_dump=pcap_dump )
		cartsdbcongestionSwitch = self.addSwitch( 's36', sw_path=sw_path, json_path=json_path, thrift_port=10095, pcap_dump=pcap_dump )
		orderscongestionSwitch = self.addSwitch( 's37', sw_path=sw_path, json_path=json_path, thrift_port=10096, pcap_dump=pcap_dump )
		ordersdbcongestionSwitch = self.addSwitch( 's38', sw_path=sw_path, json_path=json_path, thrift_port=10097, pcap_dump=pcap_dump )
		shippingcongestionSwitch = self.addSwitch( 's39', sw_path=sw_path, json_path=json_path, thrift_port=10098, pcap_dump=pcap_dump )
		queuemastercongestionSwitch = self.addSwitch( 's40', sw_path=sw_path, json_path=json_path, thrift_port=10099, pcap_dump=pcap_dump )
		rabbitmqcongestionSwitch = self.addSwitch( 's41', sw_path=sw_path, json_path=json_path, thrift_port=10100, pcap_dump=pcap_dump )
		paymentcongestionSwitch = self.addSwitch( 's42', sw_path=sw_path, json_path=json_path, thrift_port=10101, pcap_dump=pcap_dump )
		usercongestionSwitch = self.addSwitch( 's43', sw_path=sw_path, json_path=json_path, thrift_port=10102, pcap_dump=pcap_dump )
		userdbcongestionSwitch = self.addSwitch( 's44', sw_path=sw_path, json_path=json_path, thrift_port=10103, pcap_dump=pcap_dump ) 
		usersimulatorcongestionSwitch = self.addSwitch( 's45', sw_path=sw_path, json_path=json_path, thrift_port=10104, pcap_dump=pcap_dump )
		congestionswitches = [edgeroutercongestionSwitch, frontendcongestionSwitch, cataloguecongestionSwitch, cataloguedbcongestionSwitch, cartscongestionSwitch, cartsdbcongestionSwitch, orderscongestionSwitch, ordersdbcongestionSwitch, shippingcongestionSwitch, queuemastercongestionSwitch, rabbitmqcongestionSwitch, paymentcongestionSwitch, usercongestionSwitch, userdbcongestionSwitch, usersimulatorcongestionSwitch]

		# Hosts for creating congestion at various components of the system.
		edgerouterclient = self.addHost( 'h46', ip='10.0.0.244/24',mac = "00:04:00:00:00:10", cls=P4Host )
		frontendclient = self.addHost( 'h47', ip='10.0.1.244/24',mac = "00:04:00:00:01:10", cls=P4Host )
		catalogueclient = self.addHost( 'h48', ip='10.0.2.244/24',mac = "00:04:00:00:02:10", cls=P4Host )
		cataloguedbclient = self.addHost( 'h49', ip='10.0.3.244/24',mac = "00:04:00:00:03:10", cls=P4Host )
		cartsclient = self.addHost( 'h50', ip='10.0.4.244/24',mac = "00:04:00:00:04:10", cls=P4Host )
		cartsdbclient = self.addHost( 'h51', ip='10.0.5.244/24',mac = "00:04:00:00:05:10", cls=P4Host )
		ordersclient = self.addHost( 'h52', ip='10.0.6.244/24',mac = "00:04:00:00:06:10", cls=P4Host )
		ordersdbclient = self.addHost( 'h53', ip='10.0.7.244/24',mac = "00:04:00:00:07:10", cls=P4Host )
		shippingclient = self.addHost( 'h54', ip='10.0.8.244/24',mac = "00:04:00:00:08:10", cls=P4Host )
		queuemasterclient = self.addHost( 'h55', ip='10.0.9.244/24',mac = "00:04:00:00:09:10", cls=P4Host )
		rabbitmqclient = self.addHost( 'h56', ip='10.0.10.244/24',mac = "00:04:00:00:0a:10", cls=P4Host )
		paymentclient = self.addHost( 'h57', ip='10.0.11.244/24',mac = "00:04:00:00:0b:10", cls=P4Host )
		userclient = self.addHost( 'h58', ip='10.0.12.244/24',mac = "00:04:00:00:0c:10", cls=P4Host )
		userdbclient = self.addHost( 'h59', ip='10.0.13.244/24',mac = "00:04:00:00:0d:10", cls=P4Host )
		usersimulatorclient = self.addHost( 'h60', ip='10.0.14.244/24',mac = "00:04:00:00:0e:10", cls=P4Host )
		clients = [edgerouterclient, frontendclient, catalogueclient, cataloguedbclient, cartsclient, cartsdbclient, ordersclient, ordersdbclient, shippingclient, queuemasterclient, rabbitmqclient, paymentclient, userclient, userdbclient, usersimulatorclient]

		edgerouterserver = self.addHost( 'h61', ip='10.0.0.245/24',mac = "00:04:00:00:00:11", cls=P4Host )
		frontendserver = self.addHost( 'h62', ip='10.0.1.245/24',mac = "00:04:00:00:01:11", cls=P4Host )
		catalogueserver = self.addHost( 'h63', ip='10.0.2.245/24',mac = "00:04:00:00:02:11", cls=P4Host )
		cataloguedbserver = self.addHost( 'h64', ip='10.0.3.245/24',mac = "00:04:00:00:03:11", cls=P4Host )
		cartsserver = self.addHost( 'h65', ip='10.0.4.245/24',mac = "00:04:00:00:04:11", cls=P4Host )
		cartsdbserver = self.addHost( 'h66', ip='10.0.5.245/24',mac = "00:04:00:00:05:11", cls=P4Host )
		ordersserver = self.addHost( 'h67', ip='10.0.6.245/24',mac = "00:04:00:00:06:11", cls=P4Host )
		ordersdbserver = self.addHost( 'h68', ip='10.0.7.245/24',mac = "00:04:00:00:07:11", cls=P4Host )
		shippingserver = self.addHost( 'h69', ip='10.0.8.245/24',mac = "00:04:00:00:08:11", cls=P4Host )
		queuemasterserver = self.addHost( 'h70', ip='10.0.9.245/24',mac = "00:04:00:00:09:11", cls=P4Host )
		rabbitmqserver = self.addHost( 'h71', ip='10.0.10.245/24',mac = "00:04:00:00:0a:11", cls=P4Host )
		paymentserver = self.addHost( 'h72', ip='10.0.11.245/24',mac = "00:04:00:00:0b:11", cls=P4Host )
		userserver = self.addHost( 'h73', ip='10.0.12.245/24',mac = "00:04:00:00:0c:11", cls=P4Host )
		userdbserver = self.addHost( 'h74', ip='10.0.13.245/24',mac = "00:04:00:00:0d:11", cls=P4Host )
		usersimulatorserver = self.addHost( 'h75', ip='10.0.14.245/24',mac = "00:04:00:00:0e:11", cls=P4Host )
		servers = [edgerouterserver, frontendserver, catalogueserver, cataloguedbserver, cartsserver, cartsdbserver, ordersserver, ordersdbserver, shippingserver, queuemasterserver, rabbitmqserver, paymentserver, userserver, userdbserver, usersimulatorserver]

		# Add links between hosts and switches
		for integer in range(0,15):
			self.addLink( hosts[integer], switches[integer])
			self.addLink( clients[integer], switches[integer] )
			self.addLink( switches[integer], congestionswitches[integer] )
			self.addLink( servers[integer], congestionswitches[integer] )
		
	
		# Add links between the linux router and switches
		for integer in range(0,15):
			hexchar = str(integer)
			if integer == 10:
				hexchar = 'a'
			elif integer == 11:
				hexchar = 'b'
			elif integer == 12:
				hexchar = 'c'
			elif integer == 13:
				hexchar = 'd'
			elif integer == 14:
				hexchar = 'e'
			self.addLink( congestionswitches[integer], router, intfName2='r0-eth'+str(integer), addr2='00:aa:bb:cc:00:0'+hexchar, params2={'ip': '10.0.'+str(integer)+'.10/24'} )

def reddit_main(fault_no):
	seq_choice = fault_no
	print "Iteration for fault number: " + str(fault_no)
	print "-- Starting topology with programmable switches"
	reddittopo = RedditTopo(args.behavioral_exe, args.json, args.pcap_dump)
	net = Containernet(topo=reddittopo, switch=DemoSwitch, controller=None)
	net.start()
	nat = net.addHost('nat0', cls=NAT, inNamespace=False, subnet='10.0/8')
	net.addLink(nat, net.get('r0'), intfName2='r0-eth9', addr2='00:aa:bb:cc:00:ff', params2={'ip': '192.168.10.10/16'})
	nat.config()
	net.get('nat0').cmd('ip route add 192.168.10.10 dev nat0-eth0')
	net.get('nat0').cmd('ip route add 10.0.0.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.0.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.1.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.1.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.2.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.2.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.3.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.3.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.4.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.4.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.20.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.20.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.21.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.21.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('sudo ethtool --offload nat0-eth0 rx off tx off')
	net.get('nat0').cmd('sudo ethtool -K nat0-eth0 gso off')
	net.get('r0').cmd('ip route add 192.168.0.1 dev r0-eth9')

	net.get('h1').setARP('10.0.0.1','00:aa:bb:00:00:00')
	net.get('h1').setDefaultRoute('dev h1-eth0 via 10.0.0.1')
	net.get('h1').cmd('route del -net 10.0.0.0/8')
	net.get('h2').setARP('10.0.1.1','00:aa:bb:00:00:03')
	net.get('h2').setDefaultRoute('dev h2-eth0 via 10.0.1.1')
	net.get('h2').cmd('route del -net 10.0.0.0/8')
	net.get('h8').setARP('10.0.2.1','00:aa:bb:00:00:06')
	net.get('h8').setDefaultRoute('dev h8-eth0 via 10.0.2.1')
	net.get('h8').cmd('route del -net 10.0.0.0/8')
	net.get('h9').setARP('10.0.3.1','00:aa:bb:00:00:09')
	net.get('h9').setDefaultRoute('dev h9-eth0 via 10.0.3.1')
	net.get('h9').cmd('route del -net 10.0.0.0/8')
	net.get('h10').setARP('10.0.4.1','00:aa:bb:00:00:0a')
	net.get('h10').setDefaultRoute('dev h10-eth0 via 10.0.4.1')
	net.get('h10').cmd('route del -net 10.0.0.0/8')
	net.get('h11').setARP('10.0.10.1','00:aa:bb:00:00:01')
	net.get('h11').setDefaultRoute('dev eth0 via 10.0.10.1')
	net.get('h12').setARP('10.0.11.1','00:aa:bb:00:10:01')
	net.get('h12').setDefaultRoute('dev eth0 via 10.0.11.1')
	net.get('h14').setARP('10.0.12.1','00:aa:bb:00:00:04')
	net.get('h14').setDefaultRoute('dev eth0 via 10.0.12.1')
	net.get('h15').setARP('10.0.13.1','00:aa:bb:00:10:04')
	net.get('h15').setDefaultRoute('dev eth0 via 10.0.13.1')
	net.get('h17').setARP('10.0.14.1','00:aa:bb:00:00:07')
	net.get('h17').setDefaultRoute('dev eth0 via 10.0.14.1')
	net.get('h18').setARP('10.0.15.1','00:aa:bb:00:10:07')
	net.get('h18').setDefaultRoute('dev eth0 via 10.0.15.1')
	net.get('h20').setARP('10.0.16.1','00:aa:bb:00:00:0a')
	net.get('h20').setDefaultRoute('dev eth0 via 10.0.16.1')
	net.get('h21').setARP('10.0.17.1','00:aa:bb:00:10:0a')
	net.get('h21').setDefaultRoute('dev eth0 via 10.0.17.1')
	net.get('h23').setARP('10.0.18.1','00:aa:bb:00:00:0d')
	net.get('h23').setDefaultRoute('dev eth0 via 10.0.18.1')
	net.get('h24').setARP('10.0.19.1','00:aa:bb:00:10:0d')
	net.get('h24').setDefaultRoute('dev eth0 via 10.0.19.1')

	net.get('h26').setDefaultRoute('via 10.0.5.1')

	net.get('r0').setARP('10.0.0.2','00:aa:bb:00:10:02')
	net.get('r0').setARP('10.0.1.2','00:aa:bb:00:10:05')
	net.get('r0').setARP('10.0.2.2','00:aa:bb:00:10:08')
	net.get('r0').setARP('10.0.3.2','00:aa:bb:00:10:0b')
	net.get('r0').setARP('10.0.4.2','00:aa:bb:00:10:0e')
	net.get('r0').setARP('10.0.5.2','00:04:00:00:00:05')
	net.get('r0').setARP('10.0.20.2','00:aa:bb:00:10:22')
	net.get('r0').setARP('10.0.21.2','00:aa:bb:00:10:25')

	net.get('h27').setARP('10.0.20.1','00:aa:bb:00:00:20')
	net.get('h27').setDefaultRoute('dev h27-eth0 via 10.0.20.1')
	net.get('h27').cmd('route del -net 10.0.0.0/8')
	net.get('h41').setARP('10.0.40.1','00:aa:bb:00:00:21')
	net.get('h41').setDefaultRoute('dev eth0 via 10.0.40.1')
	net.get('h42').setARP('10.0.41.1','00:aa:bb:00:10:21')
	net.get('h42').setDefaultRoute('dev eth0 via 10.0.41.1')
	
	host_machines = [1,2,8,9,10,27]
	for host_machine in host_machines:
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s off" % off
			net.get('h'+str(host_machine)).cmd(cmd)

		# disable IPv6
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")

	sleep(4)
	print "-- Loading rules in all programmable switches"
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9090 < table_commands_reddit_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9091 < table_commands_cassandra_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9092 < table_commands_memcache_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9093 < table_commands_mcrouter_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9094 < table_commands_postgres_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10090 < table_commands_reddit_congestion_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10091 < table_commands_cassandra_congestion_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10092 < table_commands_memcache_congestion_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10093 < table_commands_mcrouter_congestion_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10094 < table_commands_postgres_congestion_switch.txt", shell=True)

	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9095 < table_commands_rabbit_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10095 < table_commands_rabbit_congestion_switch.txt", shell=True)
	
	sleep(1)
	print "-- Setting up distributed Reddit components"
	mainhost = net.get('h1')
	cassandrahost = net.get('h2')
	memcachehost = net.get('h8')
	mcrouterhost = net.get('h9')
	postgreshost = net.get('h10')
	rabbithost = net.get('h27')
	
	router = net.get('r0')
	redditSwitch = net.get('s3')
	print "--- Start Cassandra and Zookeeper"
	cassandrahost.cmd('sudo service zookeeper restart')
	cassandrahost.cmd('sudo service cassandra restart')
	print "--- Start all memcacheds"
	memcachehost.cmd('sudo service memcached restart')
	print "--- Start mcrouter"
	mcrouterhost.cmd('sudo service mcrouter restart')
	print "--- Start all databases"
	postgreshost.cmd('sudo service postgresql restart')
	print "--- Start rabbit mq broker"
	rabbithost.cmd('sudo service rabbitmq-server restart')
	rabbithost.cmd('sudo rabbitmqctl add_user reddit reddit')
	rabbithost.cmd('sudo rabbitmqctl set_permissions -p / reddit ".*" ".*" ".*"')
	rabbithost.cmd('sudo rabbitmq-plugins enable rabbitmq_management')
	rabbithost.cmd('sudo service rabbitmq-server restart')
	sleep(20)
	print "-- Starting Reddit server"
	mainhost.cmd('sudo reddit-stop')
	sleep(4)
	mainhost.cmd('sudo python /home/reddit/modify_code.py --choice ip --replacement '+str(args.ip))
	mainhost.cmd('cd /home/reddit/src/reddit/r2 && sudo paster serve --reload example.ini http_port=8090 &')
	sleep(10)
	print "Ready!"
	while True:
		try:
			resp = requests.get('http://reddit.local:8090/', timeout=10)
			break
		except requests.exceptions.Timeout:
			print "Time out error"
			break
		except Exception, e:
			print str(e)
			mainhost.cmd("cd /home/reddit/src/reddit/r2 && sudo paster serve --reload example.ini http_port=8090 &")
			sleep(2)
			continue
	choice = ""
	choice = str(seq_choice)
	print "-- Injecting the choosen fault from the sequence of randomly picked faults"
	if choice=="1":
		memcachehost.cmd('sudo service memcached stop')
	elif choice=="2":
		mcrouterhost.cmd("ps aux | grep -ie mcrouter | awk '{print $2}' | xargs kill -9")
	elif choice=="3":
		cassandrahost.cmd('sudo service cassandra stop')
	elif choice=="4":
		cassandrahost.cmd('sudo service zookeeper stop')
	elif choice=="6":
		rabbithost.cmd('sudo service rabbitmq-server stop')
	elif choice=="7":
		postgreshost.cmd('sudo service postgresql stop')
	elif choice=="8":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.1.2 -j DROP')
	elif choice=="9":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.2.2 -j DROP')
	elif choice=="10":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.3.2 -j DROP')
	elif choice=="11":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.4.2 -j DROP')
	elif choice=="12":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.1.2 -j DROP')
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.2.2 -j DROP')
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.3.2 -j DROP')
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.4.2 -j DROP')
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.20.2 -j DROP')
	elif choice=="13":
		router.cmd('sudo iptables -A FORWARD -p tcp -s '+args.ip+' -d 10.0.0.2 -j DROP')
	elif choice=="15":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 5050 -j DROP')
	elif choice=="16":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 11211 -j DROP')
	elif choice=="17":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 5432 -j DROP')
	elif choice=="18":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 9160 -j DROP')
	elif choice=="19":
		router.cmd('sudo iptables -A FORWARD -d 10.0.0.2 -j DROP')
	elif choice=="20":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 5672 -j DROP')
	elif choice=="22":
		client = net.get('h11')
		server = net.get('h12')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9090 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10090 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.10.244 10000 &")	
	elif choice=="23":
		client = net.get('h24')
		server = net.get('h23')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9094 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10094 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.19.245 10000 &")
	elif choice=="24":
		client = net.get('h15')
		server = net.get('h14')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9092 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10092 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.13.245 10000 &")
	elif choice=="25":
		client = net.get('h18')
		server = net.get('h17')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9093 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10093 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.15.245 10000 &")
	elif choice=="26":
		client = net.get('h21')
		server = net.get('h20')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9091 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10091 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.17.245 10000 &")
	elif choice=="27":
		client = net.get('h42')
		server = net.get('h41')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9095 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10095 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.41.245 10000 &")
	elif int(choice) <= 55:
		mainhost.cmd('sudo python /home/reddit/modify_code.py --choice '+choice)
	elif choice=="56":
		mainhost.update_resources(cpu_period=100000, cpu_quota=1000)
	elif choice=="57":
		cassandrahost.update_resources(cpu_period=100000, cpu_quota=1000)
	elif choice=="58":
		memcachehost.update_resources(cpu_period=100000, cpu_quota=1000)
	elif choice=="59":
		mcrouterhost.update_resources(cpu_period=100000, cpu_quota=1000)
	elif choice=="60":
		postgreshost.update_resources(cpu_period=100000, cpu_quota=1000)
	elif int(choice) <= 65:
		size = 25
		while True:
			strsize = str(size)+'m'
			try:
				if choice=="61":
					mainhost.update_resources(mem_limit=strsize)
				elif choice=="62":
					cassandrahost.update_resources(mem_limit=strsize)
				elif choice=="63":
					memcachehost.update_resources(mem_limit=strsize)
				elif choice=="64":
					mcrouterhost.update_resources(mem_limit=strsize)
				elif choice=="65":
					postgreshost.update_resources(mem_limit=strsize)
				break
			except Exception, e:
				size = size + 5
				continue
	elif int(choice) == 66:
		host_machine = 1
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s on" % off
			net.get('h'+str(host_machine)).cmd(cmd)
	elif int(choice) == 67:
		host_machine = 2
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s on" % off
			net.get('h'+str(host_machine)).cmd(cmd)
	elif int(choice) == 68:
		host_machine = 8
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s on" % off
			net.get('h'+str(host_machine)).cmd(cmd)
	elif int(choice) == 69:
		host_machine = 9
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s on" % off
			net.get('h'+str(host_machine)).cmd(cmd)
	elif int(choice) == 70:
		host_machine = 10
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s on" % off
			net.get('h'+str(host_machine)).cmd(cmd)
	else:
		print "Don't commit a fault, we can create it for you :)"

	print "-- Fault injected!"
	sleep(10)
		
	# os.system('wget -t 10 http://reddit.local:8090/')
	memcachehost.cmd("echo 'flush_all' | netcat 10.0.2.2 11211")
	
	# Start forwarding server.
	os.system('sudo python https_forwarding/serve.py --ip='+args.ip+' --port='+str(args.port)+' --domain='+args.domain+' &')
	if not os.path.isdir('/home/reddit/MultiuserFaults'):
		os.mkdir("/home/reddit/MultiuserFaults")
		os.mkdir("/home/reddit/MultiuserFaults/reddit")
	if not os.path.isdir('/home/reddit/MultiuserFaults/reddit/Fault'+str(fault_no)):
		os.mkdir("/home/reddit/MultiuserFaults/reddit/Fault"+str(fault_no))
	os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
	os.system('sudo rm -rf results*')
	
	os.system("sudo python create_multiuser_hits.py --port="+str(args.port)+" --domain="+args.domain)

	for port in range(0,6):
		switchport = 9090 + port
		congestionport = 10090 + port
		os.system('sudo ./record_register.sh 2048 '+str(switchport)+' regV_result_f0 &')
		os.system('sudo ./record_register.sh 2048 '+str(congestionport)+' regV_result_f0 &')
	# os.system('sudo python compress_p4logs.py &')
	serverSocket.listen(1)
	while True:
		print "Waiting for connection from UI client"
		connection, client_address = serverSocket.accept()
		print "Got a connection from UI client: " + str(client_address)
		data = ""
		data = connection.recv(16)
		if data.decode() == "Next Fault":
			tracescollected = requests.get('http://'+str(args.ip)+':16686/api/traces?service=reddit_tracing')
			tracescollected = tracescollected.json()
			with open('/home/reddit/MultiuserFaults/reddit/Fault'+str(fault_no)+'/traces.json', 'w') as f:
				json.dump(tracescollected, f)
			os.system('sudo cp *.pcap /home/reddit/MultiuserFaults/reddit/Fault'+str(fault_no))
			os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
			os.system('sudo mv results* /home/reddit/MultiuserFaults/reddit/Fault'+str(fault_no))
			os.system("sudo docker container stop jaeger")
			os.system("sudo docker container rm jaeger")
			net.stop()
			os.system("sudo rm *.pcap")
			os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo ps aux | grep -ie append_p4logs | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo ps aux | grep -ie append_p4logs | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo docker container stop cadvisor")
			os.system("sudo docker container rm cadvisor")
			break

def sockshop_main(fault_no):
	seq_choice = fault_no
	#os.mkdir("/home/reddit/sockshop/Faults/Fault"+str(fault_no))
	print "Iteration for fault number: " + str(fault_no)
	print "-- Starting topology with programmable switches"
	sockshoptopo = SockshopTopo(args.behavioral_exe, args.json, args.pcap_dump)
	net = Containernet(topo=sockshoptopo, switch=DemoSwitch, controller=None)
	net.start()
	
	# Add and configure NAT
	nat = net.addHost('nat0', cls=NAT, inNamespace=False, subnet='10.0/8')
	net.addLink(nat, net.get('r0'), intfName2='r0-eth15', addr2='00:aa:bb:cc:00:ff', params2={'ip': '192.168.10.10/16'})
	nat.config()
	net.get('nat0').cmd('ip route add 192.168.10.10 dev nat0-eth0')
	for integer in range(0,15):
		net.get('nat0').cmd('ip route add 10.0.'+str(integer)+'.2/32 dev nat0-eth0')
		net.get('nat0').cmd('arp -s 10.0.'+str(integer)+'.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('sudo ethtool --offload nat0-eth0 rx off tx off')
	net.get('nat0').cmd('sudo ethtool -K nat0-eth0 gso off')
	net.get('r0').cmd('ip route add 192.168.0.1 dev r0-eth15')
	
	# Configure ARP for hosts.
	for integer in range(0,15):
		hexchar = str(integer)
		if integer == 10:
			hexchar = 'a'
		elif integer == 11:
			hexchar = 'b'
		elif integer == 12:
			hexchar = 'c'
		elif integer == 13:
			hexchar = 'd'
		elif integer == 14:
			hexchar = 'e'
		net.get('h'+str(integer + 1)).cmd('ifconfig h'+str(integer+1)+'-eth0 10.0.'+str(integer)+'.2 netmask 255.255.255.0')
		net.get('h'+str(integer + 1)).cmd('ifconfig eth0 down')
		net.get('h'+str(integer + 1)).cmd('ifconfig h'+str(integer+1)+'-eth0 up')
		net.get('h'+str(integer + 1)).setARP('10.0.'+str(integer)+'.1','00:aa:bb:00:0'+hexchar+':00')
		net.get('h'+str(integer + 1)).cmd('route del -net 10.0.0.0/8')
		net.get('h'+str(integer + 1)).cmd('route add default gw 10.0.'+str(integer)+'.1 h'+str(integer + 1)+'-eth0')
		net.get('r0').setARP('10.0.'+str(integer)+'.2','00:aa:bb:00:1'+hexchar+':02')

		# Configure ARP for file clients and servers.
		client = 46 + integer
		server = 61 + integer
		net.get('h'+str(client)).setARP('10.0.'+str(integer)+'.1','00:aa:bb:00:0'+hexchar+':01')
		net.get('h'+str(client)).setDefaultRoute('dev eth0 via 10.0.'+str(integer)+'.1')
		net.get('h'+str(server)).setARP('10.0.'+str(integer)+'.1','00:aa:bb:00:1'+hexchar+':01')
		net.get('h'+str(server)).setDefaultRoute('dev eth0 via 10.0.'+str(integer)+'.1')
		net.get('h'+str(client)).cmd('arp -s 10.0.'+str(integer)+'.245 00:04:00:00:0'+hexchar+':11')
		net.get('h'+str(server)).cmd('arp -s 10.0.'+str(integer)+'.244 00:04:00:00:0'+hexchar+':10')

	host_machines = range(1,16)
	for host_machine in host_machines:
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s off" % off
			net.get('h'+str(host_machine)).cmd(cmd)

		# disable IPv6
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")


	print "-- Loading rules in all programmable switches"
	for subsystem in range(0,15):
		port = 9090 + subsystem
		congestionport = 10090 + subsystem
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port "+str(port)+" < sockshop_switch_commands_"+str(port)+".txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port "+str(congestionport)+" < sockshop_switch_commands_"+str(congestionport)+".txt", shell=True)
	
	sleep(1)

	for host_machine in range(1,15):
		net.get('h'+str(host_machine)).cmd('echo "'+args.ip+' jaeger" >> /etc/hosts')

	net.get('h4').cmd('./entrypoint.sh mysqld &')
	net.get('h3').cmd('./app -port=80 &')
	net.get('h6').cmd('./entrypoint.sh mongod &')
	net.get('h5').cmd('java -Djava.security.egd=file:/dev/urandom -jar app.jar --port=80 &')
	net.get('h8').cmd('./entrypoint.sh mongod &')
	net.get('h7').cmd('java -Djava.security.egd=file:/dev/urandom -jar app.jar --port=80 &')
	net.get('h9').cmd('java -Djava.security.egd=file:/dev/urandom -jar app.jar --port=80 &')
	net.get('h11').cmd('docker-entrypoint.sh rabbitmq-server &')
	net.get('h10').cmd('java -Djava.security.egd=file:/dev/urandom -jar app.jar --port=80 &')
	net.get('h14').cmd('docker-entrypoint.sh mongod --config /etc/mongodb.conf --smallfiles &')
	net.get('h13').cmd('user --port 80 &')
	net.get('h12').cmd('./app -port=80 &')
	net.get('h2').cmd('cd /usr/src/app && /usr/local/bin/npm start &')
	net.get('h1').cmd('./entrypoint.sh &')

	sleep(4)
	print "System up and ready to interact"
	# Component failures
	if fault_no >= 1 and fault_no <= 15:
		if fault_no in [5,7,9,10]:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie app | awk '{print $1}' | xargs kill -9")
		elif fault_no in [6,8,14]:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie mongod | awk '{print $2}' | xargs kill -9")
		elif fault_no == 1:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie traefik | awk '{print $1}' | xargs kill -9")
		elif fault_no in [3,12,13]:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie port | awk '{print $1}' | xargs kill -9")
		elif fault_no == 11:
			net.get('h'+str(fault_no)).cmd("rabbitmqctl stop")
		elif fault_no == 4:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie mysqld | awk '{print $2}' | xargs kill -9")
		else:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie node | awk '{print $1}' | xargs kill -9")

	# Misconfigured Router
	if fault_no >= 16 and fault_no <=30:
		net.get('r0').cmd('sudo iptables -A FORWARD -s 10.0.'+str(fault_no-16)+'.2 -p tcp -j DROP')

	# Network Congestion
	if fault_no >= 31 and fault_no <=45:
		server = net.get('h'+str(15+fault_no))
		client = net.get('h'+str(30+fault_no))
		subcomponent = fault_no - 31
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port "+str(9090 + subcomponent)+" < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port "+str(10090 + subcomponent)+" < congestion.txt", shell=True)
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0."+str(subcomponent)+".244 10000 &")
	
	if fault_no >= 46 and fault_no <= 60:
		net.get('h'+str(fault_no - 45)).update_resources(cpu_period=100000, cpu_quota=1000)

	if fault_no >= 61 and fault_no <= 75:
		size = 55
		while True:
			strsize = str(size)+'m'
			try:
				net.get('h'+str(fault_no - 60)).update_resources(mem_limit=strsize)
				break
			except Exception, e:
				size = size + 5
				continue

	if fault_no >= 76 and fault_no <= 90:
		host_machine = fault_no - 75
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s on" % off
			net.get('h'+str(host_machine)).cmd(cmd)

	# Start forwarding server.
	os.system('sudo python https_forwarding/serve_sockshop.py --ip='+args.ip+' --port='+str(args.port)+' --domain='+args.domain + ' &')
	if not os.path.isdir('/home/reddit/MultiuserFaults'):
		os.mkdir("/home/reddit/MultiuserFaults")
		os.mkdir("/home/reddit/MultiuserFaults/sockshop")
	if not os.path.isdir('/home/reddit/MultiuserFaults/sockshop'):
		os.mkdir("/home/reddit/MultiuserFaults/sockshop")
	if not os.path.isdir('/home/reddit/MultiuserFaults/sockshop/Fault'+str(fault_no)):
		os.mkdir("/home/reddit/MultiuserFaults/sockshop/Fault"+str(fault_no))
	os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
	os.system('sudo rm -rf results*')

	os.system("sudo python create_multiuser_hits.py --port="+str(args.port)+" --domain="+args.domain)

	for port in range(0,15):
		switchport = 9090 + port
		congestionport = 10090 + port
		os.system('sudo ./record_register.sh 2048 '+str(switchport)+' regV_result_f0 &')
		os.system('sudo ./record_register.sh 2048 '+str(congestionport)+' regV_result_f0 &')

	serverSocket.listen(1)
	while True:
		print "Waiting for connection from UI client"
		connection, client_address = serverSocket.accept()
		print "Got a connection from UI client: " + str(client_address)
		data = ""
		data = connection.recv(16)
		if data.decode() == "Next Fault":
			for servicename in ["sockshop_tracing","catalogue","user","payment","shipping","orders","carts"]:
				tracescollected = requests.get('http://'+str(args.ip)+':16686/api/traces?service='+servicename)
				tracescollected = tracescollected.json()
				with open('/home/reddit/MultiuserFaults/sockshop/Fault'+str(fault_no)+'/traces_'+servicename+'.json', 'w') as f:
					json.dump(tracescollected, f)
			os.system('sudo cp *.pcap /home/reddit/MultiuserFaults/sockshop/Fault'+str(fault_no))
			os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
			os.system('sudo mv results* /home/reddit/MultiuserFaults/sockshop/Fault'+str(fault_no))
			os.system("sudo docker container stop jaeger")
			os.system("sudo docker container rm jaeger")
			net.stop()
			os.system("sudo rm *.pcap")
			os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo ps aux | grep -ie append_p4logs | awk '{print $2}' | xargs sudo kill -9")
			os.system("sudo ps aux | grep -ie append_p4logs | awk '{print $2}' | xargs sudo kill -9")
			os.system("echo 'y' | sudo docker volume prune")
			os.system("sudo docker container stop cadvisor")
			os.system("sudo docker container rm cadvisor")
			break

def sockshop_test(fault_no):
	seq_choice = fault_no
	#os.mkdir("/home/reddit/sockshop/Faults/Fault"+str(fault_no))
	print "Iteration for fault number: " + str(fault_no)
	print "-- Starting topology with programmable switches"
	sockshoptopo = SockshopTopo(args.behavioral_exe, args.json, args.pcap_dump)
	net = Containernet(topo=sockshoptopo, switch=DemoSwitch, controller=None)
	net.start()
	
	# Add and configure NAT
	nat = net.addHost('nat0', cls=NAT, inNamespace=False, subnet='10.0/8')
	net.addLink(nat, net.get('r0'), intfName2='r0-eth15', addr2='00:aa:bb:cc:00:ff', params2={'ip': '192.168.10.10/16'})
	nat.config()
	net.get('nat0').cmd('ip route add 192.168.10.10 dev nat0-eth0')
	for integer in range(0,15):
		net.get('nat0').cmd('ip route add 10.0.'+str(integer)+'.2/32 dev nat0-eth0')
		net.get('nat0').cmd('arp -s 10.0.'+str(integer)+'.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('sudo ethtool --offload nat0-eth0 rx off tx off')
	net.get('nat0').cmd('sudo ethtool -K nat0-eth0 gso off')
	net.get('r0').cmd('ip route add 192.168.0.1 dev r0-eth15')
	
	# Configure ARP for hosts.
	for integer in range(0,15):
		hexchar = str(integer)
		if integer == 10:
			hexchar = 'a'
		elif integer == 11:
			hexchar = 'b'
		elif integer == 12:
			hexchar = 'c'
		elif integer == 13:
			hexchar = 'd'
		elif integer == 14:
			hexchar = 'e'
		net.get('h'+str(integer + 1)).cmd('ifconfig h'+str(integer+1)+'-eth0 10.0.'+str(integer)+'.2 netmask 255.255.255.0')
		net.get('h'+str(integer + 1)).cmd('ifconfig eth0 down')
		net.get('h'+str(integer + 1)).cmd('ifconfig h'+str(integer+1)+'-eth0 up')
		net.get('h'+str(integer + 1)).setARP('10.0.'+str(integer)+'.1','00:aa:bb:00:0'+hexchar+':00')
		net.get('h'+str(integer + 1)).cmd('route del -net 10.0.0.0/8')
		net.get('h'+str(integer + 1)).cmd('route add default gw 10.0.'+str(integer)+'.1 h'+str(integer + 1)+'-eth0')
		net.get('r0').setARP('10.0.'+str(integer)+'.2','00:aa:bb:00:1'+hexchar+':02')

		# Configure ARP for file clients and servers.
		client = 46 + integer
		server = 61 + integer
		net.get('h'+str(client)).setARP('10.0.'+str(integer)+'.1','00:aa:bb:00:0'+hexchar+':01')
		net.get('h'+str(client)).setDefaultRoute('dev eth0 via 10.0.'+str(integer)+'.1')
		net.get('h'+str(server)).setARP('10.0.'+str(integer)+'.1','00:aa:bb:00:1'+hexchar+':01')
		net.get('h'+str(server)).setDefaultRoute('dev eth0 via 10.0.'+str(integer)+'.1')
		net.get('h'+str(client)).cmd('arp -s 10.0.'+str(integer)+'.245 00:04:00:00:0'+hexchar+':11')
		net.get('h'+str(server)).cmd('arp -s 10.0.'+str(integer)+'.244 00:04:00:00:0'+hexchar+':10')


	host_machines = range(1,16)
	for host_machine in host_machines:
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s off" % off
			net.get('h'+str(host_machine)).cmd(cmd)

		# disable IPv6
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")

	print "-- Loading rules in all programmable switches"
	for subsystem in range(0,15):
		port = 9090 + subsystem
		congestionport = 10090 + subsystem
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port "+str(port)+" < sockshop_switch_commands_"+str(port)+".txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port "+str(congestionport)+" < sockshop_switch_commands_"+str(congestionport)+".txt", shell=True)
	
	sleep(1)

	for host_machine in range(1,15):
		net.get('h'+str(host_machine)).cmd('echo "'+args.ip+' jaeger" >> /etc/hosts')

	net.get('h4').cmd('./entrypoint.sh mysqld &')
	net.get('h3').cmd('./app -port=80 &')
	net.get('h6').cmd('./entrypoint.sh mongod &')
	net.get('h5').cmd('java -Djava.security.egd=file:/dev/urandom -jar app.jar --port=80 &')
	net.get('h8').cmd('./entrypoint.sh mongod &')
	net.get('h7').cmd('java -Djava.security.egd=file:/dev/urandom -jar app.jar --port=80 &')
	net.get('h9').cmd('java -Djava.security.egd=file:/dev/urandom -jar app.jar --port=80 &')
	net.get('h11').cmd('docker-entrypoint.sh rabbitmq-server &')
	net.get('h10').cmd('java -Djava.security.egd=file:/dev/urandom -jar app.jar --port=80 &')
	net.get('h14').cmd('docker-entrypoint.sh mongod --config /etc/mongodb.conf --smallfiles &')
	net.get('h13').cmd('user --port 80 &')
	net.get('h12').cmd('./app -port=80 &')
	net.get('h2').cmd('cd /usr/src/app && /usr/local/bin/npm start &')
	net.get('h1').cmd('./entrypoint.sh &')

	sleep(4)
	print "System up and ready to interact"
	# Component failures
	if fault_no >= 1 and fault_no <= 15:
		if fault_no in [5,7,9,10]:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie app | awk '{print $1}' | xargs kill -9")
		elif fault_no in [6,8,14]:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie mongod | awk '{print $2}' | xargs kill -9")
		elif fault_no == 1:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie traefik | awk '{print $1}' | xargs kill -9")
		elif fault_no in [3,12,13]:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie port | awk '{print $1}' | xargs kill -9")
		elif fault_no == 11:
			net.get('h'+str(fault_no)).cmd("rabbitmqctl stop")
		elif fault_no == 4:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie mysqld | awk '{print $2}' | xargs kill -9")
		else:
			net.get('h'+str(fault_no)).cmd("ps aux | grep -ie node | awk '{print $1}' | xargs kill -9")

	# Misconfigured Router
	if fault_no >= 16 and fault_no <=30:
		net.get('r0').cmd('sudo iptables -A FORWARD -s 10.0.'+str(fault_no-16)+'.2 -p tcp -j DROP')

	# Network Congestion
	if fault_no >= 31 and fault_no <=45:
		server = net.get('h'+str(15+fault_no))
		client = net.get('h'+str(30+fault_no))
		subcomponent = fault_no - 31
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port "+str(9090 + subcomponent)+" < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port "+str(10090 + subcomponent)+" < congestion.txt", shell=True)
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0."+str(subcomponent)+".244 &")
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0."+str(subcomponent)+".244 &")
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0."+str(subcomponent)+".244 &")
	
	CLI(net)
	os.system("sudo docker container stop jaeger")
	os.system("sudo docker container rm jaeger")
	net.stop()
	os.system("sudo rm *.pcap")
	os.system("echo 'y' | sudo docker volume prune")

def reddit_test(fault_no):
	seq_choice = fault_no
	print "Iteration for fault number: " + str(fault_no)
	print "-- Starting topology with programmable switches"
	reddittopo = RedditTopo(args.behavioral_exe, args.json, args.pcap_dump)
	net = Containernet(topo=reddittopo, switch=DemoSwitch, controller=None)
	net.start()
	nat = net.addHost('nat0', cls=NAT, inNamespace=False, subnet='10.0/8')
	net.addLink(nat, net.get('r0'), intfName2='r0-eth9', addr2='00:aa:bb:cc:00:ff', params2={'ip': '192.168.10.10/16'})
	nat.config()
	net.get('nat0').cmd('ip route add 192.168.10.10 dev nat0-eth0')
	net.get('nat0').cmd('ip route add 10.0.0.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.0.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.1.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.1.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.2.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.2.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.3.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.3.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.4.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.4.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.20.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.20.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('ip route add 10.0.21.2/32 dev nat0-eth0')
	net.get('nat0').cmd('arp -s 10.0.21.2 00:aa:bb:cc:00:ff')
	net.get('nat0').cmd('sudo ethtool --offload nat0-eth0 rx off tx off')
	net.get('nat0').cmd('sudo ethtool -K nat0-eth0 gso off')
	net.get('r0').cmd('ip route add 192.168.0.1 dev r0-eth9')

	net.get('h1').setARP('10.0.0.1','00:aa:bb:00:00:00')
	net.get('h1').setDefaultRoute('dev h1-eth0 via 10.0.0.1')
	net.get('h1').cmd('route del -net 10.0.0.0/8')
	net.get('h2').setARP('10.0.1.1','00:aa:bb:00:00:03')
	net.get('h2').setDefaultRoute('dev h2-eth0 via 10.0.1.1')
	net.get('h2').cmd('route del -net 10.0.0.0/8')
	net.get('h8').setARP('10.0.2.1','00:aa:bb:00:00:06')
	net.get('h8').setDefaultRoute('dev h8-eth0 via 10.0.2.1')
	net.get('h8').cmd('route del -net 10.0.0.0/8')
	net.get('h9').setARP('10.0.3.1','00:aa:bb:00:00:09')
	net.get('h9').setDefaultRoute('dev h9-eth0 via 10.0.3.1')
	net.get('h9').cmd('route del -net 10.0.0.0/8')
	net.get('h10').setARP('10.0.4.1','00:aa:bb:00:00:0a')
	net.get('h10').setDefaultRoute('dev h10-eth0 via 10.0.4.1')
	net.get('h10').cmd('route del -net 10.0.0.0/8')
	net.get('h11').setARP('10.0.10.1','00:aa:bb:00:00:01')
	net.get('h11').setDefaultRoute('dev eth0 via 10.0.10.1')
	net.get('h12').setARP('10.0.11.1','00:aa:bb:00:10:01')
	net.get('h12').setDefaultRoute('dev eth0 via 10.0.11.1')
	net.get('h14').setARP('10.0.12.1','00:aa:bb:00:00:04')
	net.get('h14').setDefaultRoute('dev eth0 via 10.0.12.1')
	net.get('h15').setARP('10.0.13.1','00:aa:bb:00:10:04')
	net.get('h15').setDefaultRoute('dev eth0 via 10.0.13.1')
	net.get('h17').setARP('10.0.14.1','00:aa:bb:00:00:07')
	net.get('h17').setDefaultRoute('dev eth0 via 10.0.14.1')
	net.get('h18').setARP('10.0.15.1','00:aa:bb:00:10:07')
	net.get('h18').setDefaultRoute('dev eth0 via 10.0.15.1')
	net.get('h20').setARP('10.0.16.1','00:aa:bb:00:00:0a')
	net.get('h20').setDefaultRoute('dev eth0 via 10.0.16.1')
	net.get('h21').setARP('10.0.17.1','00:aa:bb:00:10:0a')
	net.get('h21').setDefaultRoute('dev eth0 via 10.0.17.1')
	net.get('h23').setARP('10.0.18.1','00:aa:bb:00:00:0d')
	net.get('h23').setDefaultRoute('dev eth0 via 10.0.18.1')
	net.get('h24').setARP('10.0.19.1','00:aa:bb:00:10:0d')
	net.get('h24').setDefaultRoute('dev eth0 via 10.0.19.1')

	net.get('h26').setDefaultRoute('via 10.0.5.1')

	net.get('r0').setARP('10.0.0.2','00:aa:bb:00:10:02')
	net.get('r0').setARP('10.0.1.2','00:aa:bb:00:10:05')
	net.get('r0').setARP('10.0.2.2','00:aa:bb:00:10:08')
	net.get('r0').setARP('10.0.3.2','00:aa:bb:00:10:0b')
	net.get('r0').setARP('10.0.4.2','00:aa:bb:00:10:0e')
	net.get('r0').setARP('10.0.5.2','00:04:00:00:00:05')
	net.get('r0').setARP('10.0.20.2','00:aa:bb:00:10:22')
	net.get('r0').setARP('10.0.21.2','00:aa:bb:00:10:25')

	net.get('h27').setARP('10.0.20.1','00:aa:bb:00:00:20')
	net.get('h27').setDefaultRoute('dev h27-eth0 via 10.0.20.1')
	net.get('h27').cmd('route del -net 10.0.0.0/8')
	net.get('h41').setARP('10.0.40.1','00:aa:bb:00:00:21')
	net.get('h41').setDefaultRoute('dev eth0 via 10.0.40.1')
	net.get('h42').setARP('10.0.41.1','00:aa:bb:00:10:21')
	net.get('h42').setDefaultRoute('dev eth0 via 10.0.41.1')
	
	host_machines = [1,2,8,9,10,27]
	for host_machine in host_machines:
		for off in ["rx", "tx", "sg"]:
			cmd = "ethtool --offload h"+str(host_machine)+"-eth0 %s off" % off
			net.get('h'+str(host_machine)).cmd(cmd)

		# disable IPv6
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.all.disable_ipv6=1")
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.default.disable_ipv6=1")
		net.get('h'+str(host_machine)).cmd("sysctl -w net.ipv6.conf.lo.disable_ipv6=1")

	sleep(4)
	print "-- Loading rules in all programmable switches"
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9090 < table_commands_reddit_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9091 < table_commands_cassandra_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9092 < table_commands_memcache_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9093 < table_commands_mcrouter_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9094 < table_commands_postgres_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10090 < table_commands_reddit_congestion_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10091 < table_commands_cassandra_congestion_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10092 < table_commands_memcache_congestion_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10093 < table_commands_mcrouter_congestion_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10094 < table_commands_postgres_congestion_switch.txt", shell=True)

	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9095 < table_commands_rabbit_switch.txt", shell=True)
	subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10095 < table_commands_rabbit_congestion_switch.txt", shell=True)
	
	sleep(1)
	print "-- Setting up distributed Reddit components"
	mainhost = net.get('h1')
	cassandrahost = net.get('h2')
	memcachehost = net.get('h8')
	mcrouterhost = net.get('h9')
	postgreshost = net.get('h10')
	rabbithost = net.get('h27')
	
	router = net.get('r0')
	redditSwitch = net.get('s3')
	print "--- Start Cassandra and Zookeeper"
	cassandrahost.cmd('sudo service zookeeper restart')
	cassandrahost.cmd('sudo service cassandra restart')
	print "--- Start all memcacheds"
	memcachehost.cmd('sudo service memcached restart')
	print "--- Start mcrouter"
	mcrouterhost.cmd('sudo service mcrouter restart')
	print "--- Start all databases"
	postgreshost.cmd('sudo service postgresql restart')
	print "--- Start rabbit mq broker"
	rabbithost.cmd('sudo service rabbitmq-server restart')
	rabbithost.cmd('sudo rabbitmqctl add_user reddit reddit')
	rabbithost.cmd('sudo rabbitmqctl set_permissions -p / reddit ".*" ".*" ".*"')
	rabbithost.cmd('sudo rabbitmq-plugins enable rabbitmq_management')
	rabbithost.cmd('sudo service rabbitmq-server restart')
	sleep(10)
	print "-- Starting Reddit server"
	mainhost.cmd('sudo reddit-stop')
	mainhost.cmd('sudo python /home/reddit/modify_code.py --choice ip --replacement '+str(args.ip))
	mainhost.cmd('cd /home/reddit/src/reddit/r2 && sudo paster serve --reload example.ini http_port=8090 &')
	sleep(10)
	print "Ready!"
	choice = ""
	choice = str(seq_choice)
	print "-- Injecting the choosen fault from the sequence of randomly picked faults"
	if choice=="1":
		memcachehost.cmd('sudo service memcached stop')
	elif choice=="2":
		mcrouterhost.cmd("ps aux | grep -ie mcrouter | awk '{print $2}' | xargs kill -9")
	elif choice=="3":
		cassandrahost.cmd('sudo service cassandra stop')
	elif choice=="4":
		cassandrahost.cmd('sudo service zookeeper stop')
	elif choice=="6":
		rabbithost.cmd('sudo service rabbitmq-server stop')
	elif choice=="7":
		postgreshost.cmd('sudo service postgresql stop')
	elif choice=="8":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.1.2 -j DROP')
	elif choice=="9":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.2.2 -j DROP')
	elif choice=="10":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.3.2 -j DROP')
	elif choice=="11":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.4.2 -j DROP')
	elif choice=="12":
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.1.2 -j DROP')
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.2.2 -j DROP')
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.3.2 -j DROP')
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.4.2 -j DROP')
		router.cmd('sudo iptables -A FORWARD -p tcp -s 10.0.0.2 -d 10.0.20.2 -j DROP')
	elif choice=="13":
		router.cmd('sudo iptables -A FORWARD -p tcp -s '+args.ip+' -d 10.0.0.2 -j DROP')
	elif choice=="15":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 5050 -j DROP')
	elif choice=="16":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 11211 -j DROP')
	elif choice=="17":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 5432 -j DROP')
	elif choice=="18":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 9160 -j DROP')
	elif choice=="19":
		router.cmd('sudo iptables -A FORWARD -d 10.0.0.2 -j DROP')
	elif choice=="20":
		router.cmd('sudo iptables -A FORWARD -p tcp --destination-port 5672 -j DROP')
	elif choice=="22":
		client = net.get('h11')
		server = net.get('h12')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9090 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10090 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.10.244 &")	
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.10.244 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.10.244 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.10.244 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.10.244 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.10.244 &")
	elif choice=="23":
		client = net.get('h24')
		server = net.get('h23')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9094 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10094 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.19.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.19.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.19.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.19.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.19.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.19.245 &")
	elif choice=="24":
		client = net.get('h15')
		server = net.get('h14')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9092 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10092 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.13.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.13.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.13.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.13.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.13.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.13.245 &")
	elif choice=="25":
		client = net.get('h18')
		server = net.get('h17')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9093 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10093 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.15.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.15.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.15.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.15.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.15.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.15.245 &")
	elif choice=="26":
		client = net.get('h21')
		server = net.get('h20')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9091 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10091 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.17.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.17.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.17.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.17.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.17.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.17.245 &")
	elif choice=="27":
		client = net.get('h42')
		server = net.get('h41')
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 9095 < congestion.txt", shell=True)
		subprocess.call("~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port 10095 < congestion.txt", shell=True)
		client.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/receiver 10000 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.41.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.41.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.41.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.41.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.41.245 &")
		server.cmd("/home/reddit/NLP_Debugging_Assistant/datagrump/sender 10.0.41.245 &")
	elif int(choice) <= 55:
		mainhost.cmd('sudo python /home/reddit/modify_code.py --choice '+choice)
	else:
		print "Don't commit a fault, we can create it for you :)"

	print "-- Fault injected!"
	
	os.system('wget -t 10 http://reddit.local:8090/')
	memcachehost.cmd("echo 'flush_all' | netcat 10.0.2.2 11211")
	CLI(net)
	os.system("sudo docker container stop jaeger")
	os.system("sudo docker container rm jaeger")
	net.stop()
	os.system("sudo rm *.pcap")

def signal_handler(sig, frame):
	global args
	fault_no = current_fault
	if current_app == "sockshop":
		for servicename in ["sockshop_tracing","catalogue","user","payment","shipping","orders","carts"]:
			tracescollected = requests.get('http://'+str(args.ip)+':16686/api/traces?service='+servicename)
			tracescollected = tracescollected.json()
			with open('/home/reddit/MultiuserFaults/sockshop/Fault'+str(fault_no)+'/traces_'+servicename+'.json', 'w') as f:
				json.dump(tracescollected, f)
		os.system('sudo cp *.pcap /home/reddit/MultiuserFaults/sockshop/Fault'+str(fault_no))
		os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
		os.system('sudo mv results* /home/reddit/MultiuserFaults/sockshop/Fault'+str(fault_no))
		os.system("sudo docker container stop jaeger")
		os.system("sudo docker container rm jaeger")
		os.system("sudo rm *.pcap")
		os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
		os.system("echo 'y' | sudo docker volume prune")
		os.system("sudo ps aux | grep -ie append_p4logs | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo ps aux | grep -ie append_p4logs | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo docker container stop cadvisor")
		os.system("sudo docker container rm cadvisor")
		os.system("sudo mn -c")
		os.system('sudo tar -zvcf ../MultiuserFaults/sockshop_'+str(args.port)+'.tar.gz ../MultiuserFaults/sockshop/')
		sys.exit(0)
	elif current_app == "reddit":
		tracescollected = requests.get('http://'+str(args.ip)+':16686/api/traces?service=reddit_tracing')
		tracescollected = tracescollected.json()
		with open('/home/reddit/MultiuserFaults/reddit/Fault'+str(fault_no)+'/traces.json', 'w') as f:
			json.dump(tracescollected, f)
		os.system('sudo cp *.pcap /home/reddit/MultiuserFaults/reddit/Fault'+str(fault_no))
		os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
		os.system('sudo mv results* /home/reddit/MultiuserFaults/reddit/Fault'+str(fault_no))
		os.system("sudo docker container stop jaeger")
		os.system("sudo docker container rm jaeger")
		os.system("sudo rm *.pcap")
		os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo ps aux | grep -ie append_p4logs | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo ps aux | grep -ie append_p4logs | awk '{print $2}' | xargs sudo kill -9")
		os.system("sudo docker container stop cadvisor")
		os.system("sudo docker container rm cadvisor")
		os.system("sudo mn -c")
		os.system('sudo tar -zvcf ../MultiuserFaults/reddit_'+str(args.port)+'.tar.gz ../MultiuserFaults/reddit/')
		sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

if __name__ == '__main__':
	os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")
	os.system("sudo ps aux | grep -ie record_register | awk '{print $2}' | xargs sudo kill -9")	
	os.system("sudo docker container stop jaeger")
	os.system("sudo docker container rm jaeger")
	os.system("sudo rm *.pcap")
	os.system("sudo docker container stop cadvisor")
	os.system("sudo docker container rm cadvisor")
	os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
	os.system("sudo ps aux | grep -ie https_forwarding | awk '{print $2}' | xargs sudo kill -9")
	os.system("sudo mn -c")
	os.system("sudo rm traces*")
	os.system("sudo rm -rf results*")
	os.system("echo 'y' | sudo docker volume prune")
	setLogLevel( 'info' )
	if args.app_choice.lower()=="reddit":
		for fault in args.faults:
			os.system("sudo docker run -d --name jaeger -e COLLECTOR_ZIPKIN_HTTP_PORT=9411 -p 5775:5775/udp -p 6831:6831/udp -p 6832:6832/udp -p 5778:5778 -p 16686:16686 -p 14268:14268 -p 9411:9411 jaegertracing/all-in-one:1.13")
			os.system("sudo docker run --volume=/:/rootfs:ro --volume=/var/run:/var/run:ro --volume=/sys:/sys:ro --volume=/var/lib/docker/:/var/lib/docker:ro --volume=/dev/disk/:/dev/disk:ro --publish=15000:8080 --detach=true --name=cadvisor gcr.io/google-containers/cadvisor:latest")
			current_app = "reddit"
			current_fault = fault
			reddit_main(fault)
		os.system('sudo tar -zvcf ../MultiuserFaults/reddit_'+str(args.port)+'.tar.gz ../MultiuserFaults/reddit/')
	elif args.app_choice.lower()=="sockshop":
		for fault in args.faults:
			os.system("sudo docker run -d --name jaeger -e COLLECTOR_ZIPKIN_HTTP_PORT=9411 -p 5775:5775/udp -p 6831:6831/udp -p 6832:6832/udp -p 5778:5778 -p 16686:16686 -p 14268:14268 -p 9411:9411 jaegertracing/all-in-one:1.13")
			os.system("sudo docker run --volume=/:/rootfs:ro --volume=/var/run:/var/run:ro --volume=/sys:/sys:ro --volume=/var/lib/docker/:/var/lib/docker:ro --volume=/dev/disk/:/dev/disk:ro --publish=15000:8080 --detach=true --name=cadvisor gcr.io/google-containers/cadvisor:latest")
			current_app = "sockshop"
			current_fault = fault
			sockshop_main(fault)
		os.system('sudo tar -zvcf ../MultiuserFaults/sockshop_'+str(args.port)+'.tar.gz ../MultiuserFaults/sockshop/')
	elif args.app_choice.lower()=="sockshop_interactive":
		for fault in args.faults:
			os.system("sudo docker run -d --name jaeger -e COLLECTOR_ZIPKIN_HTTP_PORT=9411 -p 5775:5775/udp -p 6831:6831/udp -p 6832:6832/udp -p 5778:5778 -p 16686:16686 -p 14268:14268 -p 9411:9411 jaegertracing/all-in-one:1.13")
			current_app = "sockshop_interactive"
			current_fault = fault
			sockshop_test(fault)
	elif args.app_choice.lower()=="reddit_interactive":
		for fault in args.faults:
			os.system("sudo docker run -d --name jaeger -e COLLECTOR_ZIPKIN_HTTP_PORT=9411 -p 5775:5775/udp -p 6831:6831/udp -p 6832:6832/udp -p 5778:5778 -p 16686:16686 -p 14268:14268 -p 9411:9411 jaegertracing/all-in-one:1.13")
			current_app = "reddit_interactive"
			current_fault = fault
			reddit_test(fault)
	else:
		print "Invalid app choice. Choose Reddit (or) Sockshop"
		sys.exit(0)


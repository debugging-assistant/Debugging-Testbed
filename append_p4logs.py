import os
import sys
import time
import argparse
import json

parser = argparse.ArgumentParser(description='Script to reduce marple log sizes')
parser.add_argument('--port', help='P4 switch port', type=int, action="store", required=True)
parser.add_argument('--fileno', help='File number of generated log', type=int, action="store", required=True)
args = parser.parse_args()

switchport = args.port
fileno = args.fileno
try:
	if os.path.isdir('results'+str(switchport)):
		timestamps = []
		if os.path.isfile('results'+str(switchport)+'/cache_timestamps.json'):
			with open('results'+str(switchport)+'/cache_timestamps.json','r') as inputfile:
				timestamps = json.load(inputfile)
		file_content = []
		with open('results'+str(switchport)+'/'+str(fileno)+'.txt','r') as inputfile:
			lines = []
			for line in inputfile:
				if line.startswith('RuntimeCmd: reg'):
					lines.append(line[line.index(':')+2:])
				if line.startswith('RuntimeCmd: times'):
					lines.append(line[line.index(':')+2:])
					try:
						timestamp = int(line[line.index('=')+2:-1])
						if timestamp != 0 and timestamp not in timestamps:
							file_content = file_content + lines
							timestamps.append(timestamp)
						lines = []
					except Exception, e:
						lines = []
						break
		with open('results'+str(switchport)+'/cache_timestamps.json','w') as outpufile:
			json.dump(timestamps, outpufile)
		if os.path.isfile('results'+str(switchport)+'/p4logs.txt'):
			with open('results'+str(switchport)+'/p4logs.txt','a') as outpufile:
				outpufile.writelines(file_content)
		else:
			with open('results'+str(switchport)+'/p4logs.txt','w') as outpufile:
				outpufile.writelines(file_content)
		os.remove('results'+str(switchport)+'/'+str(fileno)+'.txt')
except Exception, e:
	sys.exit(0)

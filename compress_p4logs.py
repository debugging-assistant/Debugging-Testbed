import os
import sys
import time

time.sleep(45)
while True:
	for port in range(0,15):
		switchport = 9090 + port
		congestionport = 10090 + port
		if os.path.isdir('results'+str(switchport)):
			timestamps = []
			file_content = []
			files = [int(f[0:f.index('.')]) for f in os.listdir('results'+str(switchport)) if os.path.isfile(os.path.join('results'+str(switchport), f))]
			files.sort()
			exclude = []
			for fileno in files:
				with open('results'+str(switchport)+'/'+str(fileno)+'.txt','r') as inputfile:
					lines = []
					for line in inputfile:
						if line.startswith('RuntimeCmd: reg'):
							lines.append(line)
						if line.startswith('RuntimeCmd: times'):
							lines.append(line)
							try:
								timestamp = int(line[line.index('=')+2:-1])
								if timestamp != 0 and timestamp not in timestamps:
									file_content = file_content + lines
									timestamps.append(timestamp)
								lines = []
							except Exception, e:
								lines = []
								exclude.append(fileno)
								break
					if len(lines) > 0:
						exclude.append(fileno)
			with open('results'+str(switchport)+'/0.txt','w') as outpufile:
				outpufile.writelines(file_content)
			for fileno in files[1:]:
				if fileno not in exclude:
					os.remove('results'+str(switchport)+'/'+str(fileno)+'.txt')
		if os.path.isdir('results'+str(congestionport)):
			timestamps = []
			file_content = []
			files = [int(f[0:f.index('.')]) for f in os.listdir('results'+str(congestionport)) if os.path.isfile(os.path.join('results'+str(congestionport), f))]
			files.sort()
			exclude = []
			for fileno in files:
				with open('results'+str(congestionport)+'/'+str(fileno)+'.txt','r') as inputfile:
					lines = []
					for line in inputfile:
						if line.startswith('RuntimeCmd: reg'):
							lines.append(line)
						if line.startswith('RuntimeCmd: times'):
							lines.append(line)
							try:
								timestamp = int(line[line.index('=')+2:-1])
								if timestamp != 0 and timestamp not in timestamps:
									file_content = file_content + lines
									timestamps.append(timestamp)
								lines = []
							except Exception, e:
								lines = []
								exclude.append(fileno)
								break
					if len(lines) > 0:
						exclude.append(fileno)
			with open('results'+str(congestionport)+'/0.txt','w') as outpufile:
				outpufile.writelines(file_content)
			for fileno in files[1:]:
				if fileno not in exclude:
					os.remove('results'+str(congestionport)+'/'+str(fileno)+'.txt')
	time.sleep(30)
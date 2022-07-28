import os
import sys

# For switches connecting the system hosts
for subsystem in range(0,15):
	port = 9090 + subsystem
	hexchar = str(subsystem)
	if subsystem == 10:
		hexchar = 'a'
	elif subsystem == 11:
		hexchar = 'b'
	elif subsystem == 12:
		hexchar = 'c'
	elif subsystem == 13:
		hexchar = 'd'
	elif subsystem == 14:
		hexchar = 'e'
	outputfile = open('sockshop_switch_commands_'+str(port)+'.txt','w')
	outputfile.write('set_queue_rate 1000\n')
	outputfile.write('table_add ipv4_match Set_nhop 10.0.'+str(subsystem)+'.2/32 => 10.0.'+str(subsystem)+'.2 1\n')
	outputfile.write('table_add dmac Set_dmac 10.0.'+str(subsystem)+'.2 => 00:04:00:00:00:0'+hexchar+'\n')
	outputfile.write('table_add smac Set_smac 1 => 00:aa:bb:00:0'+hexchar+':00\n')
	outputfile.write('table_add ipv4_match Set_nhop 10.0.'+str(subsystem)+'.244/32 => 10.0.'+str(subsystem)+'.244 2\n')
	outputfile.write('table_add dmac Set_dmac 10.0.'+str(subsystem)+'.244 => 00:04:00:00:0'+hexchar+':10\n')
	outputfile.write('table_add smac Set_smac 2 => 00:aa:bb:00:0'+hexchar+':01\n')
	outputfile.write('table_add ipv4_match Set_nhop 10.0.'+str(subsystem)+'.245/32 => 10.0.'+str(subsystem)+'.245 3\n')
	outputfile.write('table_add dmac Set_dmac 10.0.'+str(subsystem)+'.245 => 00:aa:bb:00:1'+hexchar+':00\n')
	outputfile.write('table_add smac Set_smac 3 => 00:aa:bb:00:0'+hexchar+':02\n')
	for othersubsystem in range(0,15):
		if othersubsystem==subsystem:
			continue
		outputfile.write('table_add ipv4_match Set_nhop 10.0.'+str(othersubsystem)+'.2/32 => 10.0.'+str(othersubsystem)+'.2 3\n')
		outputfile.write('table_add dmac Set_dmac 10.0.'+str(othersubsystem)+'.2 => 00:aa:bb:00:1'+hexchar+':00\n')
	outputfile.write('table_add ipv4_match Set_nhop 192.168.122.118/32 => 192.168.122.118 3\n')
	outputfile.write('table_add dmac Set_dmac 192.168.122.118 => 00:aa:bb:00:1'+hexchar+':00\n')
	outputfile.write('table_add ipv4_match Set_nhop 192.168.122.119/32 => 192.168.122.119 3\n')
	outputfile.write('table_add dmac Set_dmac 192.168.122.119 => 00:aa:bb:00:1'+hexchar+':00\n')
	outputfile.write('table_add ipv4_match Set_nhop 192.168.122.120/32 => 192.168.122.120 3\n')
	outputfile.write('table_add dmac Set_dmac 192.168.122.120 => 00:aa:bb:00:1'+hexchar+':00\n')
	outputfile.write('table_add ipv4_match Set_nhop 192.168.122.121/32 => 192.168.122.121 3\n')
	outputfile.write('table_add dmac Set_dmac 192.168.122.121 => 00:aa:bb:00:1'+hexchar+':00\n')
	outputfile.close()

# For switches connecting the above switches to the router
for subsystem in range(0,15):
	port = 10090 + subsystem
	hexchar = str(subsystem)
	if subsystem == 10:
		hexchar = 'a'
	elif subsystem == 11:
		hexchar = 'b'
	elif subsystem == 12:
		hexchar = 'c'
	elif subsystem == 13:
		hexchar = 'd'
	elif subsystem == 14:
		hexchar = 'e'
	outputfile = open('sockshop_switch_commands_'+str(port)+'.txt','w')
	outputfile.write('set_queue_rate 1000\n')
	outputfile.write('table_add ipv4_match Set_nhop 10.0.'+str(subsystem)+'.2/32 => 10.0.'+str(subsystem)+'.2 1\n')
	outputfile.write('table_add dmac Set_dmac 10.0.'+str(subsystem)+'.2 => 00:aa:bb:00:0'+hexchar+':02\n')
	outputfile.write('table_add smac Set_smac 1 => 00:aa:bb:00:1'+hexchar+':00\n')
	outputfile.write('table_add ipv4_match Set_nhop 10.0.'+str(subsystem)+'.244/32 => 10.0.'+str(subsystem)+'.244 1\n')
	outputfile.write('table_add dmac Set_dmac 10.0.'+str(subsystem)+'.244 => 00:aa:bb:00:0'+hexchar+':02\n')
	outputfile.write('table_add smac Set_smac 2 => 00:aa:bb:00:1'+hexchar+':01\n')
	outputfile.write('table_add ipv4_match Set_nhop 10.0.'+str(subsystem)+'.245/32 => 10.0.'+str(subsystem)+'.245 2\n')
	outputfile.write('table_add dmac Set_dmac 10.0.'+str(subsystem)+'.245 => 00:04:00:00:0'+hexchar+':11\n')
	outputfile.write('table_add smac Set_smac 3 => 00:aa:bb:00:1'+hexchar+':02\n')
	for othersubsystem in range(0,15):
		if othersubsystem==subsystem:
			continue
		outputfile.write('table_add ipv4_match Set_nhop 10.0.'+str(othersubsystem)+'.2/32 => 10.0.'+str(othersubsystem)+'.2 3\n')
		outputfile.write('table_add dmac Set_dmac 10.0.'+str(othersubsystem)+'.2 => 00:aa:bb:cc:00:0'+hexchar+'\n')
	outputfile.write('table_add ipv4_match Set_nhop 192.168.122.118/32 => 192.168.122.118 3\n')
	outputfile.write('table_add dmac Set_dmac 192.168.122.118 => 00:aa:bb:cc:00:0'+hexchar+'\n')
	outputfile.write('table_add ipv4_match Set_nhop 192.168.122.119/32 => 192.168.122.119 3\n')
	outputfile.write('table_add dmac Set_dmac 192.168.122.119 => 00:aa:bb:cc:00:0'+hexchar+'\n')
	outputfile.write('table_add ipv4_match Set_nhop 192.168.122.120/32 => 192.168.122.120 3\n')
	outputfile.write('table_add dmac Set_dmac 192.168.122.120 => 00:aa:bb:cc:00:0'+hexchar+'\n')
	outputfile.write('table_add ipv4_match Set_nhop 192.168.122.121/32 => 192.168.122.121 3\n')
	outputfile.write('table_add dmac Set_dmac 192.168.122.121 => 00:aa:bb:cc:00:0'+hexchar+'\n')
	outputfile.close()
#!/bin/bash

size=$1
sizem1=$((size-1))

cmdfile="read_register_CLI_cmds"$2".txt"
rm -f $cmdfile
for i in `seq 1 $sizem1`
do
    echo "register_read $3 $i" >> $cmdfile
    echo "register_read regK_result_f0 $i" >> $cmdfile
    echo "register_read regK_result_f1 $i" >> $cmdfile
    echo "register_read regK_result_f2 $i" >> $cmdfile
    echo "register_read regK_result_f3 $i" >> $cmdfile
    echo "register_read regK_result_f4 $i" >> $cmdfile
    echo "register_read times $i" >> $cmdfile
done

mkdir -p results$2

j=0
while [ $j -ne 43200 ]
do
outfile="results"$2/$j".txt"
mkdir -p results$2
cat $cmdfile | ~/behavioral-model/targets/simple_switch/sswitch_CLI --thrift-port $2 > $outfile
sudo python append_p4logs.py --port $2 --fileno $j
sleep 2
j=$((j+1))
done

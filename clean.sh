sudo mn -c
sudo rm *.pcap
for i in $( ps ax | awk '/record_register/ {print $1}' ); do kill ${i}; done
sudo rm -rf results*
for i in $( ps ax | awk '/https_forwarding/ {print $1}' ); do kill ${i}; done
sudo docker container stop jaeger
sudo docker container rm jaeger
sudo docker container stop cadvisor
sudo docker container rm cadvisor
sudo docker volume prune
sudo rm read_register_CLI_cmds*
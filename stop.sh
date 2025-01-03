sudo systemctl stop kubelet
sudo systemctl stop crio
sudo kill -9 $(ps aux | grep kube-apiserver | grep -v grep | awk '{print $2}')
FROM spark:4.0.1-python3

USER root

RUN apt-get update && apt-get install -y sudo curl git unzip python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt                                                                                                                                  
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

COPY spark-dependencies.sh /tmp/spark-dependencies.sh                                                                                                                        
RUN chmod +x /tmp/spark-dependencies.sh && \                                                                                                                                 
    /tmp/spark-dependencies.sh && \                                                                                                                                          
    rm /tmp/spark-dependencies.sh                                                                                                                                            

COPY data_pipelines /opt/spark/data_pipelines      

WORKDIR /opt/spark
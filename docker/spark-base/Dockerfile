FROM spark:4.0.1-python3

USER root

RUN apt-get update && apt-get install -y sudo curl git unzip python3-pip && \
    rm -rf /var/lib/apt/lists/*

COPY docker/spark-base/requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt

COPY docker/spark-base/spark-dependencies.sh /tmp/spark-dependencies.sh                                                                                                                        
RUN chmod +x /tmp/spark-dependencies.sh && \                                                                                                                                 
    /tmp/spark-dependencies.sh && \                                                                                                                                          
    rm /tmp/spark-dependencies.sh                                                                                                                                            

COPY data_pipelines /opt/spark/data_pipelines

# Set PYTHONPATH so utilities can be imported
ENV PYTHONPATH="/opt/spark/data_pipelines:${PYTHONPATH}"

WORKDIR /opt/spark
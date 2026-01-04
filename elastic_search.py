import requests
from requests.auth import HTTPBasicAuth

def elastic_search(url, username, password, start_time, end_time, max_results=10000):
    query = {
        "query": {
            "range": {
                "timestamp": {
                    "gte": start_time.isoformat(timespec='milliseconds'),
                    "lt": end_time.isoformat(timespec='milliseconds')
                }
            }
        },
        "size": max_results
    }
    
    response = requests.post(url, 
                           auth=HTTPBasicAuth(username, password),
                           headers={"Content-Type": "application/json"},
                           json=query)
    
    response.raise_for_status()
    
    result = response.json()
    if 'hits' not in result or 'hits' not in result['hits']:
        raise ValueError(f"Unexpected response format from Elasticsearch: {result}")
    
    return result['hits']['hits']

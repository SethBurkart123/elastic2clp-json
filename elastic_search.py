import requests
from requests.auth import HTTPBasicAuth
import logging

logger = logging.getLogger(__name__)

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
    
    logger.debug(f"Elasticsearch request - URL: {url}, Time range: {start_time.isoformat()} to {end_time.isoformat()}, Max results: {max_results}")
    logger.debug(f"Query body: {query}")
    
    try:
        response = requests.post(url, 
                               auth=HTTPBasicAuth(username, password),
                               headers={"Content-Type": "application/json"},
                               json=query,
                               timeout=30)
        
        logger.debug(f"Response status: {response.status_code}")
        
        response.raise_for_status()
        
        result = response.json()
        if 'hits' not in result or 'hits' not in result['hits']:
            logger.error(f"Unexpected response format from Elasticsearch. Response: {result}")
            raise ValueError(f"Unexpected response format from Elasticsearch: {result}")
        
        hits = result['hits']['hits']
        hit_count = len(hits)
        total = result['hits'].get('total', {})
        total_hits = total.get('value', hit_count) if isinstance(total, dict) else total if total else hit_count
        logger.debug(f"Retrieved {hit_count} hits (total available: {total_hits})")
        
        return hits
    except requests.exceptions.HTTPError as e:
        if e.response is not None:
            try:
                error_detail = f" Response body: {e.response.json()}"
            except (ValueError, AttributeError):
                error_detail = f" Response text: {e.response.text[:500]}"
        else:
            error_detail = ""
        logger.error(f"HTTP error for URL {url}: {e.response.status_code if e.response else 'N/A'} - {str(e)}{error_detail}")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error for URL {url}: {type(e).__name__} - {str(e)}")
        raise

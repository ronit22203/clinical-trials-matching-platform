import requests
import json

def check_ct_gov_version():
    """
    Checks the ClinicalTrials.gov API v2 version and data freshness.
    """
    url = "https://clinicaltrials.gov/api/v2/version"
    
    try:
        # 1. Make the HTTP GET request
        # We set a timeout to prevent the agent from hanging if the API is down
        response = requests.get(url, timeout=10)
        
        # 2. Check if the request was successful (Status Code 200)
        response.raise_for_status()
        
        # 3. Parse the JSON response
        data = response.json()
        
        # 4. Extract key information
        api_version = data.get("apiVersion", "Unknown")
        data_timestamp = data.get("dataTimestamp", "Unknown")
        
        print(f"✓ API Reachable ")
        print(f"- API Version: {api_version}")
        print(f"- Data Last Updated: {data_timestamp}")
        
        return data

    except requests.exceptions.RequestException as e:
        print(f"API Connection Failed: {e}")
        return None

if __name__ == "__main__":
    check_ct_gov_version()
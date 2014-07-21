from requests.auth import HTTPBasicAuth
URL = "http://localhost:14000/api/"
HEADERS = {'content-type': 'application/json'}
AUTH = HTTPBasicAuth('user', 'notthispassword')

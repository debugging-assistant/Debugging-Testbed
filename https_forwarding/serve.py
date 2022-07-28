from flask import Flask, request, Response, redirect, url_for, send_file
from flask import render_template
import requests
import json
from socket import *
import sys
import argparse
import time

parser = argparse.ArgumentParser(description='HTTP request forwarding to the containernet setup')
parser.add_argument('--ip', help='IP address of the machine',type=str, action="store", required=True)
parser.add_argument('--port', help='Port where the frontend receives HTTPS requests at',type=int, action="store", required=True)
parser.add_argument('--domain', help='Domain name of the server', type=str, action="store", required=True)
args = parser.parse_args()

app = Flask(__name__, static_url_path='/stupid_static')

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>',  methods=['POST','GET','HEAD'])
def load(path):
	try:
		resp = requests.request(method=request.method, url=request.url.replace(request.host_url, 'http://reddit.local:8090/'), headers={key: value for (key, value) in request.headers if key != 'Host'}, data=request.get_data(), cookies=request.cookies, timeout=20)
		excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection', 'x-frame-options']
		headers = [(name, value) for (name, value) in resp.raw.headers.items() if name.lower() not in excluded_headers]
		if resp.status_code >= 400:
			resp.status_code = 200
		modified_headers = []
		for header in headers:
			modified_header =  (header[0] , header[1].replace('reddit.local:8090',args.domain+':'+str(args.port)).replace('; HttpOnly',''))
			modified_headers.append(modified_header)
		response = Response(resp.content.replace('https://reddit.local', 'https://'+args.domain+':'+str(args.port)).replace('http://reddit.local:8090','https://'+args.domain+':'+str(args.port)).replace('reddit.local:8090',args.domain+':'+str(args.port)), resp.status_code , modified_headers)
	except requests.exceptions.Timeout:
		print "Time out error"
		print "Hit Exception"
		return json.dumps({'Response Timed Out':True}), 500, {'ContentType': 'application/json'}
	except Exception, e:
		print "Time out error"
		print "Hit Exception"
		return json.dumps({'Unable to connect':True}), 500, {'ContentType': 'application/json'}

	return response    


# run the application
if __name__ == "__main__":
	app.run(debug=True, host=args.ip, port=80)

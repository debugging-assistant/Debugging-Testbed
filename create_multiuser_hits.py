import argparse

parser = argparse.ArgumentParser(description='Mturk multiuser HIT creator')
parser.add_argument('--port', help='HTTPS port for the experiment on turk', type=int, action="store", required=True)
parser.add_argument('--domain',help='Domain name of the server', type=str, action="store", required=True)
args = parser.parse_args()

import boto3

region_name = ''
# Keys here
aws_access_key_id = ''
aws_secret_access_key = ''

endpoint_url = 'https://mturk-requester.us-east-1.amazonaws.com'

mturk = boto3.client(
    'mturk',
    endpoint_url=endpoint_url,
    region_name=region_name,
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
)

# This will return $10,000.00 in the MTurk Developer Sandbox
print(mturk.get_account_balance()['AvailableBalance'])

question = open(name='external_questions.xml',mode='r').read()
question = question.replace('mturkexperimentnas.tk',str(args.domain)+':'+str(args.port))
new_hit = mturk.create_hit(
    Title = 'Report issues in a webpage load. BONUS $0.1 on correct responses. Survey',
    Description = 'You will be presented with a webpage. You have to perform actions from instructions on the page and you have to report any issues you observe with that page load. If you give correct responses we will grant a $0.1 bonus for each correct assignment.',
    Keywords = 'text, quick, labeling, website, webpage, survey, experiment, bug, short, easy, issue, report, performance',
    Reward = '0.20',
    MaxAssignments = 5,
    LifetimeInSeconds = 86400,
    AssignmentDurationInSeconds = 600,
    AutoApprovalDelayInSeconds = 3*86400,
    Question = question,
    QualificationRequirements=[{
	'QualificationTypeId': "00000000000000000040",
	'Comparator': "GreaterThan",
	'IntegerValues':[2000]
    },]
)
print "A new HIT has been created. You can preview it here:"
print "https://worker.mturk.com/mturk/preview?groupId=" + new_hit['HIT']['HITGroupId']
print "HITID = " + new_hit['HIT']['HITId'] + " (Use to Get Results)"

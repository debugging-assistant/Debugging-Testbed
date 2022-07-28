import argparse

parser = argparse.ArgumentParser(description='Mturk HIT creator')
parser.add_argument('--port', help='HTTPS port for the experiment on turk', type=int, action="store", required=True)
args = parser.parse_args()

import boto3

region_name = ''
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
if args.port != 443:
    question = question.replace('mturkexperimentnas.tk','mturkexperimentnas.tk:'+str(args.port))
new_hit = mturk.create_hit(
    Title = 'Report issues in reddit webpage load (< ~3 min)',
    Description = 'You will be presented with a webpage and you have to report any issues you observe with that page load and follow the instructions presented on the same page.',
    Keywords = 'text, quick, labeling, website, webpage, issue, report, performance',
    Reward = '0.3',
    MaxAssignments = 1,
    LifetimeInSeconds = 86400,
    AssignmentDurationInSeconds = 600,
    AutoApprovalDelayInSeconds = 86400,
    Question = question,
    QualificationRequirements=[{
	'QualificationTypeId': "2F1QJWKUDD8XADTFD2Q0G6UTO95ALH",
	'Comparator': "Exists",
    },]
)
print "A new HIT has been created. You can preview it here:"
print "https://worker.mturk.com/mturk/preview?groupId=" + new_hit['HIT']['HITGroupId']
print "HITID = " + new_hit['HIT']['HITId'] + " (Use to Get Results)"

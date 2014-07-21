import json
import requests
import urllib
import config
import fractions
import logging
import time
from CFDCamperLogo import LOGO

url = config.URL 
headers = config.HEADERS
auth = config.AUTH
UNIT = 10**8
FEE_PER_KB=20000 #Increase our chance of getting into the block on time
FEED_ADDRESS = 'n3HFSdueD43w7tF48qfExZNykfrrVR2Yf9' #Feed Address to Camp
MIN_TARGET_SIZE = 10 * UNIT #Minimum wager amount of target bet
MIN_ATTACK_DISTANCE = 900 #in seconds, time before next broadcast to start attack
MIN_ATTACK_SIZE = 1.5 #minimum normalized difference between broadcasts to attack for
SAFETY_CONSTANT= 2.5 #Adjust for how much the price might change between the matching attack and the broadcast block for small differences
SAFETY_RATIO = .75 #percent based adjustment for large movements
SAFETY_THRESHOLD = 8 #Threshold for switching between safety_constant and safety_ratio
MY_ADDRESSES = ['mhtp9Fpt1Citcfhua34DrhZQMTwMF2qS7V', 'moSG49871W5D1CmscFJjJgYyH2BnFwLpJD', 'mtAMogTagoRwJkcDxduBY8iMnxxehofqrX', 'n4No9RNhAGmkJT54LmcsenagfrGXbvm8r6', 'msRd43qcfz7vfmRAJks2f58caiSzS94Hoa', 'mrwDQYWweppb7siEDm7w2sbjpBDWX7gEJm']
LAST_BROADCAST = None 
LAST_BROADCAST_TIMESTAMP= None
CAST_INTERVAL = 3600 #Either gotten from enhanced info or established manually
BET_TYPE_NAME = {0: 'Bull', 1: 'Bear'}


F = fractions.Fraction

logging.basicConfig(
    level = logging.INFO,
    format = '%(asctime)s %(levelname)s %(message)s',
)
class LoopyAccessList(list): 
    def __init__(self, *args, **kwargs): 
        list.__init__(self, *args)
        self.counter = 0
    def get(self, ):
        self.counter += 1
        key = self.counter % len(self)
        return self[key - 1]

MY_ADDRESSES = LoopyAccessList(MY_ADDRESSES) 

def qNum(num_items):
   return ','.join('?' for i in range(num_items))
   
    #Don't attack you're own open wagers that didn't match
def getOpenBets():  
    bindings = [FEED_ADDRESS] + MY_ADDRESSES
    query = 'SELECT * FROM bets WHERE (status == "open") AND (feed_address == ?) AND (source NOT IN (%s))' %(qNum(len(MY_ADDRESSES)))
    payload = {'method': 'sql', 'params': {'query': query, 'bindings': bindings}, 'jsonrpc': '2.0', 'id': 0}
    response = requests.post(url, data=json.dumps(payload), headers=headers, auth=auth).json()
    return response['result']
def trim(x):
    return round(x / 10**8, 4)

def getLastBroadcast():
    bindings = [FEED_ADDRESS]
    query= 'SELECT * FROM broadcasts WHERE (status = "valid" AND source = ?) ORDER BY tx_index DESC'
    payload = {'method': 'sql', 'params': {'query': query, 'bindings': bindings}, 'jsonrpc': '2.0', 'id': 0}
    response = requests.post(url, data=json.dumps(payload), headers=headers, auth=auth).json()
    return response['result'][0] 

#for Estimating the value of the next broadcast #Must be tailored to the specific Feed
def getRealTimePrice(): 
    price,timestamp = btcTicker() 
    return price 
    
def btcTicker():
        data = json.loads(urllib.request.urlopen('https://api.coindesk.com/v1/bpi/currentprice.json').read().decode('utf-8'))
        dataPrice= float(data['bpi']['USD']['rate'])
        dataTime = data['time']['updated']
        return dataPrice, dataTime    

def doBet(params):
    default_params = {'allow_unconfirmed_inputs': True, 'target_value':0}
    params.update(default_params)
    payload = { "method": "do_bet", "params": params, "jsonrpc": "2.0", "id": 0} 
    response = requests.post(url, data=json.dumps(payload), headers=headers, auth=auth).json()
    return response

def getRunningInfo(): 
    payload = { "method": "get_running_info", "params": {}, "jsonrpc": "2.0", "id": 0}
    response = requests.post(url, data=json.dumps(payload), headers=headers, auth=auth).json()
    return response['result']

print(LOGO)
STARTUP = True
target_tracked = {}
while True: 
    if not STARTUP: 
        logging.info("sleeping for 120 seconds")
        time.sleep(120)
    STARTUP= False
    try:
        current_block = getRunningInfo()['last_block']['block_index']
    except:
        logging.info("Could not connect to Counterpartyd RPC") 
        continue
    last_broadcast = getLastBroadcast()
    if not LAST_BROADCAST or (last_broadcast['tx_hash'] != LAST_BROADCAST['tx_hash']):
        LAST_BROADCAST = last_broadcast
        initial_value = LAST_BROADCAST['value'] 
        LAST_BROADCAST_TIMESTAMP = time.time() if LAST_BROADCAST_TIMESTAMP else last_broadcast['timestamp']
        logging.info("Added New Broadcast, Value: {0}, Time: {1}".format(initial_value, time.ctime(LAST_BROADCAST_TIMESTAMP)))
    current_time = time.time()
    estimate_till_next_broadcast = (CAST_INTERVAL - (current_time - LAST_BROADCAST_TIMESTAMP ))
    logging.info("Estimated time till next broadcast: {}".format(estimate_till_next_broadcast))
    if estimate_till_next_broadcast > MIN_ATTACK_DISTANCE: continue
    open_bets  = getOpenBets()
    logging.info("Found {0} open bets at Feed {1}".format(len(open_bets), FEED_ADDRESS))
    if not open_bets: continue
    target_bets = {}
    for bet in open_bets: 
        if bet['wager_remaining'] < MIN_TARGET_SIZE: continue
        if not bet['bet_type'] in [0,1]: continue
        if (bet['counterwager_quantity'] / bet['wager_quantity']) > 5: continue
        bet_expire_remaining = bet['expiration'] - (current_block - bet['block_index']) 
        if (bet_expire_remaining - 1) <  (estimate_till_next_broadcast / (60 * 10)): continue
        target_bets[bet['tx_hash']] = bet 
    if not target_bets: continue
    logging.info("Found {0} targets at Feed {1}".format(len(open_bets), FEED_ADDRESS))
    current_price = getRealTimePrice() 
    price_difference = current_price - initial_value
    if SAFETY_CONSTANT< price_difference < SAFETY_THRESHOLD: 
        safe_difference = (price_difference - SAFETY_CONSTANT)
    elif -SAFETY_THRESHOLD < price_difference < -SAFETY_CONSTANT: 
        safe_difference = (price_difference + SAFETY_CONSTANT)
    elif -SAFETY_CONSTANT< price_difference < SAFETY_CONSTANT: 
        safe_difference = 0 
    else:
        safe_difference = (price_difference * SAFETY_RATIO)
    logging.info("Initital Value {0}, Real time price {1}, Price difference {2}, Estimated safe difference {3}".format(initial_value, current_price, price_difference, safe_difference))
    if abs(safe_difference) < MIN_ATTACK_SIZE: continue
    for target in target_bets.values(): 
        if (target['bet_type'] == 0 and safe_difference > 0) or (target['bet_type'] == 1 and safe_difference < 0):
            logging.info("Target type {0}, Estimated Safe Difference {1} --Skipping".format(BET_TYPE_NAME[target['bet_type']], safe_difference))
            continue
        else:
            logging.info("Target type {0}, Estimated Safe Difference {1} --Targetting".format(BET_TYPE_NAME[target['bet_type']], safe_difference))
        try:
            if (time.time() - target_tracked[target['tx_hash']]['timestamp']) < 20*60: pass 
            else: raise Exception 
        except:
            target_tracked[target['tx_hash']] = {'timestamp': time.time(), 'estimated_wager_remaining': target['wager_remaining']}
        print("target_wager_remaining %s" %target_tracked[target['tx_hash']]['estimated_wager_remaining'])
        while target_tracked[target['tx_hash']]['estimated_wager_remaining'] >= 0:
        #if True:
            time.sleep(2) 
            target_inverse_odds = F(target['counterwager_quantity']/ target['wager_quantity']) 
            if target_tracked[target['tx_hash']]['estimated_wager_remaining'] > safe_difference * UNIT:
                wager_quantity = round((safe_difference * UNIT) * target_inverse_odds)
                counterwager_quantity = round((safe_difference * UNIT))
            else: 
                wager_quantity = round(target_tracked[target['tx_hash']]['estimated_wager_remaining'] * target_inverse_odds)
                counterwager_quantity = round(target_tracked[target['tx_hash']]['estimated_wager_remaining'])
            leverage = target['leverage']
            deadline = target['deadline'] 
            bet_type = 0 if target['bet_type'] == 1 else 1
            expiration = round((MIN_ATTACK_DISTANCE * 2) / (60* 10))
            source= MY_ADDRESSES.get()
            params = {'fee_per_kb': FEE_PER_KB, 'source': source, 'expiration': expiration, 'bet_type': bet_type, 'deadline': deadline, 'leverage': leverage, 'counterwager_quantity': counterwager_quantity, 'wager_quantity': wager_quantity, 'feed_address': FEED_ADDRESS}
            #print(params)
            try:
                tx_hash = doBet(params)['result']
            except: continue
            if tx_hash:
                target_tracked[target['tx_hash']]['estimated_wager_remaining'] = target_tracked[target['tx_hash']]['estimated_wager_remaining'] - round(safe_difference * UNIT)
                logging.info("ATTACK: Target Address {0}, Estimated wager_remaining {1}, Actual wager_remaining {2}, Wager_quantity {3}".format(target['source'], trim(target_tracked[target['tx_hash']]['estimated_wager_remaining']), trim(target['wager_remaining']), trim(wager_quantity)))
                logging.info("ATTACK: HASH {}".format(tx_hash))

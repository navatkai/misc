#!/usr/bin/python

from threading import Timer
import time
import requests
import json
import pycurl
from StringIO import StringIO
import web
from web import form
import subprocess
import datetime
import logging
import re

URL = 'https://developer-api.nest.com/devices/thermostats/k4Uaevi2-wbStry7CbKddrElelcE_V-c'

urls = (
  '/', 'Home',
  '/timer', 'HeatTimer',
  '/stoptimer', 'StopTimer',
  '/stop', 'Stop',
  '/auth/nest', 'Auth',
  '/index', 'Index',
  '/(.*)', 'Index',
)

if __name__ == "__main__": 
    from web.wsgiserver import CherryPyWSGIServer
    ssl_cert = '/home/pi/server.crt'
    ssl_key = '/home/pi/server.key'
    CherryPyWSGIServer.ssl_certificate = ssl_cert
    CherryPyWSGIServer.ssl_private_key = ssl_key
    app = web.application(urls, globals())
    
    # Global vars
    web.history = ''
    web.auth_code = ''
    web.access_token = ''
    web.expires_in = 0
    web.timer = None
    web.timer_start_time = ''
    web.timer_duration = 0
    web.render = ''
    web.therm_stats = None
    web.pattern = re.compile('Start (\d+)min')

    logging.basicConfig(filename='ctest.log', 
                        format='[%(asctime)s] %(levelname)s %(funcName)s %(lineno)d %(message)s', datefmt='%m%d%Y %H:%M:%S',
                        filemode='a+', level=logging.DEBUG)

    app.run()  

myform = form.Form(
    form.Textbox("duration", form.notnull, 
                 form.regexp('\d+', 'Must be a digit'),
                 form.Validator('Must be between 5 and 20', lambda x:int(x) >= 5 and int(x) <= 20),
                 description="Timer duration (mins)"),
#    form.Textarea('dashboard', readonly=True, description=''),
    form.Button("btn", value="submit_value", html="Start Timer", type='submit'), 
)

# Textbox
#               <input type="text" id="duration" value="10" name="duration"  style="height:70px; font-size: 40px"/>

class Home:
  home_form = """<form method="post">
              <br><input type="submit" name="btn" value="Start 5min" style="height:100px; width:15em; font-size: 40px"/> 
              <br><input type="submit" name="btn" value="Start 10min" style="height:100px; width:15em; font-size: 40px"/> 
              <br><input type="submit" name="btn" value="Start 15min" style="height:100px; width:15em; font-size: 40px"/> 
              <br><input type="submit" name="btn" value="Start 20min" style="height:100px; width:15em; font-size: 40px"/> 
              <br><input type="button" value="Close this window" onclick="window.open('', '_self', ''); window.close();" style="height:100px; width:15em; font-size: 40px"/> """

  stop_form = """<form method="post">
              <br><input type="submit" name="btn" value="Stop" style="height:100px; width:15em; font-size: 40px"/>
              <br><input type="button" value="Close this window" onclick="window.open('', '_self', ''); window.close();" style="height:100px; width:15em; font-size: 40px"/>
              </form> """

  def GET(self):
    web.history = '/'
    f = ''
    if web.timer is None:
      f = self.home_form
      logging.info('Rendering home page with timer off')
    else:
      f = self.stop_form
      logging.info('Rendering home page with timer on')
    web.render = RenderHeatStats()
    body = web.render + f
    return """<html><body>""" + body + "</body></html>"
            
  def POST(self):
    logging.debug('In Post')
    data = web.input()
    match = web.pattern.match(data.btn)
    if match:
        duration = int(match.group(1))
        logging.info('Setting timer for %d min', duration)
        msg = StartHeatTimer(duration)
        logging.info('Heat timer started. Msg: %s', msg)
        body = web.render + self.stop_form + msg
    elif data.btn == 'Stop':
        if web.timer:
            web.timer.cancel()
            (rcode, error) = SetTempUsingCall(web.access_token, 59, True)
            logging.info('Timer cancelled. Msg: %s', error)
            msg = '<h1/>Heat timer Cancelled. Status: %s' % error
        else:
            logging.info('Nothing to stop as timer not running')
            msg = '<h1/>Heat timer not running'
        body = web.render + msg
    else:
        logging.error('How did I get here')
        body = web.render + '<h2/>How did I get here'
    return "<html><body>" + body + "</body></html>"

# Stops timer and the thermostat
class StopTimer:
  def GET(self):
    if web.timer:
        web.timer.cancel()
        (rcode, error) = SetTempUsingCall(web.access_token, 59, True)
        return '<h1/>Heat timer Cancelled. Status: %s' % error
    else:
        return '<h1/>Heat timer not running'

class Stop:
  def GET(self):
    msg = ''
    if web.timer:
        web.timer.cancel() 
        msg = '<h1/>Heat timer Cancelled.'
    (rcode, error) = SetTempUsingCall(web.access_token, 50, True)
    return msg + '<BR>Status: %s' % error

class Auth:
  def GET(self):
    logging.debug('data: %s', web.data())    
    logging.debug('web.ctx: %s', web.ctx)
    logging.debug('query: %s' , web.ctx.query)
    logging.debug('auth_code: %s', web.input().code)
    web.auth_code = web.input().code
    logging.debug('custom referer: %s', web.history)

    (rcode, result) = GetAccessToken(web.auth_code)
    if not rcode:
      return
    (web.access_token, web.expires_in) = result
    logging.debug('access_token: %s', web.access_token)
    logging.debug('expired_in: %d', web.expires_in)
    raise web.seeother(web.history)

class Index:
  def GET(self):
    logging.debug('Rendering home page')
    web.history = '/'
    return RenderHeatStats()

    # print 'data:' , web.data()
    #return "Hello, Nest!"

def StartHeatTimer(time):
      try:
        logging.debug('StartHeatTimer %s', web.ctx.fullpath)
        if time > 20: 
          return "<h1>Timer duration must be under 21 mins."

        if web.timer is not None:
          return "<h1/>Heat timer already running"

        temperature = 68
        if web.therm_stats:
            temperature = web.therm_stats['ambient_temperature_f'] + 2
        (rcode, error) = SetTempUsingCall(web.access_token, temperature, False)
        if not rcode:
          logging.error( "SetTempUsingCall returned %s check logs", error)
          return "<h1>SetTempUsingCall returned %s check logs" % error

        logging.debug('Starting timer')
        web.timer_start_time = datetime.datetime.now().strftime("%I:%M%p")
        web.timer_duration = time

        web.timer = Timer(time * 60, SetTempUsingCall, args=[web.access_token, 50, True])
        web.timer.start()
        return "<h1/>" + error + "<br>Heat timer set for %d mins!" % time
      except Exception as e:
          message = ''
          if hasattr(e, 'message'):
              message = e.message
          else:
              message = e
          logging.error('history: %s message: %s', web.history, message)
          return ("<h1/>%s" % message) 

def RenderHeatStats():
    #? Check if auth_code is empty or is expired or force_codes
    #? Check if access code is empty or is expired
    #?  Redirect as below
    logging.debug('In RenderHeatStats')
    if len(web.auth_code) == 0 or len(web.access_token) == 0:
      logging.debug("Getting access token")
      raise web.seeother('https://home.nest.com/login/oauth2?client_id=c01bc9c5-c06a-42d6-be61-695fdb7dda9d&state=49382')
    
    (rcode, thermostat_state) = read(web.access_token)
    msg = ''
    if not rcode:
      logging.info('Failure %s', thermostat_state)
      msg = thermostat_state
    else:
      msg = """<h1/>Ambient Temperature: %d
               <br>Target temperature: %d
               <br>hvac_mode: %s
               <br>hvac_state: %s
               <br>is_online: %d
               <br>fan_timer_active: %d""" % (
          thermostat_state['ambient_temperature_f'], 
          thermostat_state['target_temperature_f'], 
          thermostat_state['hvac_mode'], 
          thermostat_state['hvac_state'], 
          thermostat_state['is_online'], 
          thermostat_state['fan_timer_active'])

      web.therm_stats = thermostat_state
      logging.info('Success %s', msg)

    if web.timer:
        msg = """%s<br>Heat Timer started at %s
                 <br>Heat Timer duration %d mins""" % (msg, web.timer_start_time, web.timer_duration)
  
    return msg

class HeatTimer:
    def GET(self):
        logging.debug('Processing timer request %s', web.ctx.fullpath)
        web.history = web.ctx.fullpath
        logging.debug('history: ', web.history)
        return StartHeatTimer(int(web.input().time))

def PrintResponseForRequestslib(response):
  rcode = False
  if response.status_code == requests.codes.ok:
    logging.debug('success')
    rcode = True
  logging.debug("Response: %s", response)
  msg = json.dumps(response.json, indent=2, sort_keys=True)
  logging.debug("JSON: %s", msg)
  return (rcode, msg)

def PrintResponse(c, buffer):
  rcode = False
  if c.getinfo(c.RESPONSE_CODE) == 200:
    logging.debug('success')
    rcode = True
  print('Status: %d' % c.getinfo(c.RESPONSE_CODE))
  print(buffer.getvalue())
  return (rcode, buffer.getvalue())

def ReadUsingRequests():
  logging.debug('In read_old')
  headers = {'Content-Type': 'application/json', 'Authorization': web.access_token}
  r = requests.get(URL, headers=headers)
  PrintResponseForRequestslib(r)
  return r.json

def read(access_token):
  logging.debug('reading device')
  buffer = StringIO()
  c = pycurl.Curl()
  c.setopt(c.URL, URL)
  c.setopt(c.WRITEFUNCTION, buffer.write)
  auth = 'Authorization: ' + access_token
  c.setopt(c.HTTPHEADER, ['Content-Type: application/json', auth])
  c.setopt(c.FOLLOWLOCATION, True)
  c.perform()

  (rcode, msg) = PrintResponse(c, buffer)
  res = json.loads(buffer.getvalue())
  c.close()
  return (rcode, res) if rcode else (rcode, msg)

def read_all_devices(access_token):
  headers = {'Content-Type': 'application/json', 'Authorization' : access_token}
  r = requests.get('https://developer-api.nest.com/devices', headers=headers)
  PrintResponse(r)

def set_temp(access_token, temp, has_ended):
  data = '{"target_temperature_f": %d, "hvac_mode": "heat" }' % temp
  buffer = StringIO()
  indata = StringIO(data)
  c = pycurl.Curl()
  c.setopt(c.URL, URL)
  c.setopt(c.WRITEFUNCTION, buffer.write)
  c.setopt(c.READFUNCTION, indata.read)
  c.setopt(c.INFILESIZE, len(data))
  c.setopt(c.HTTPHEADER, ['Content-Type: application/json', 'Authorization: ' + access_token])
  c.setopt(c.FOLLOWLOCATION, True)
  c.setopt(c.VERBOSE, True)
  c.setopt(c.PUT, True)
  c.perform()

  PrintResponse(c, buffer)

  res = json.loads(buffer.getvalue())
  c.close()

  if has_ended:
      web.timer = None

def SetHVACModeUsingCall(access_token):
  cmd = ['curl', '-L', '-X', 'PUT', '-H', 'Content-Type: application/json', '-H', 'Authorization: %s' % access_token, '-d', '{"hvac_mode": "heat"}', URL]  
  output = subprocess.check_output(cmd)
  o = json.loads(output)
  ret = (False, 'Unknown Error')
  if 'error' in o:
    logging.error('Error setting hvac_mode %s', o['error'])
    ret = (False, o['error'])
  elif 'hvac_mode' in o:
    logging.info('Set hvac_mode to %s', o['hvac_mode'])
    ret = (True, 'Successfully set hvac_mode to %s' % o['hvac_mode'])
  return ret

def SetTempUsingCall(access_token, temp, has_ended):
  (rcode, error) = SetHVACModeUsingCall(access_token)
  if not rcode:
      #? authentication
      logging.error('%s', error)
      if has_ended:
        web.timer = Timer(180, SetTempUsingCall, args=[access_token, 50, True])
        web.timer.start()
        logging.error('Restarted stop timer for 180 secs because of %s', error)
      return (rcode, error)
  
  cmd = ['curl', '-L', '-X', 'PUT', '-H', 
         'Content-Type: application/json', '-H', 
         'Authorization: %s' % access_token, '-d', 
         '{"target_temperature_f": %d}' % temp, 
         URL]
  output = subprocess.check_output(cmd)
  o = json.loads(output)
  ret = (False, 'Unknown Error')
  if 'error' in o:
    logging.error('Error setting target temp %s', o['error'])
    if has_ended:
        web.timer = Timer(180, SetTempUsingCall, args=[access_token, 50, True])
        web.timer.start()
    ret = (False, o['error'])
  elif 'target_temperature_f' in o:
    logging.info('Set target temperature to %dF', o['target_temperature_f'])
    ret = (True, 'Successfully set to %dF' % o['target_temperature_f'])

  if has_ended:
    if ret[0]:
      web.timer = None
      logging.info('Stopped the heat timer')
    else:
      logging.error('Restarted stop timer for 180 secs because of %s', ret[1])

  return ret

def GetAccessToken(auth_code):
  logging.debug('In GetAccessToken()')
  data = {'code': auth_code, 'client_id':'c01bc9c5-c06a-42d6-be61-695fdb7dda9d','client_secret':'OcAfImmCMQDUYwKthiFZWfPvN','grant_type':'authorization_code'}
  url = 'https://api.home.nest.com/oauth2/access_token'
  r = requests.post(url, params=data)
  (rcode, msg) = PrintResponseForRequestslib(r)
  if rcode:
    msg = (str('Bearer %s' % r.json['access_token'].strip()),
           r.json['expires_in'])
  return (rcode, msg)


###############
# How to generate ssl keys and certificate
# openssl genrsa -des3 -out server.key 1024
# openssl req -new -key server.key -out server.csr
# openssl x509 -req -days 365 -in server.csr -signkey server.key -out server.crt

### TODO
#+ set correct date on the raspbian
# record time of when structure was fetched
# Show current time and how old the structure is
# cache thermostat structure
# avoid fetching structure if cached was last fetched x mins ago.
# avoid changing hvac mode if it is heat already
# when turning the heat on, increment ambient temp by 2 degrees instead of setting it to 68.

# detect need for authentication/authorization and redirect
# handle blocked response

# When on schedule, if ambient temperature is above X then skip the heat.

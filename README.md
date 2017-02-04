# Custom Nest Thermostat Controller

My house looses heat during the winter and I can't rely on the ability of the thermostat, if on, to automatically turn off when the ambient temperature reaches the target temperature. (It just takes forever)

So I decided to write this web app which is accessible from any browser on the local network to turn on the heat for the next 5, 10, 15 or 20 minutes. I have is a computer (raspberry pi) on the local network that is always on. I run this python app which serves the web page and provides basic controls to turn on the heat for a certain duration.

# Keep the program running after closing terminal
nohup nest_timer.py

disown -h %1

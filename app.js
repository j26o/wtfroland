

var express = require('express'),
  config = require('./config/config'),
  http = require('http'),
  socketio = require('socket.io');

var app = express();

require('./config/express')(app, config);

app.listen(config.port);


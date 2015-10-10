var express = require('express'),
  config = require('./config/config'),
  http = require('http'),
  io = require('socket.io')(http);


var app = express();

require('./config/express')(app, config);

io.on('connection', function(){
	console.log('io connection');
});

app.listen(config.port);
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


// var server = require('http').createServer(app);
// var io = require('socket.io')(server);
// io.on('connection', function(){ /* … */ });
// server.listen(3000);

$(function() {

	var nav = $('#nav'), who = $('#who'), lab = $('#lab');

    nav.children('a').on({
    	'click': function(e){
    		e.preventDefault();

    		var t = $(this);
    		if(t.hasClass('who')) {
    			who.toggleClass('active');
    		}
    	}
    });

    who.find('.close').on({
    	'click': function(){
    		who.removeClass('active');
    	}
    });

    lab.attr('src', 'lab/chat-app/');
});
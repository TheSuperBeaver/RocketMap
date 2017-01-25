
var captchaOnly = '<div class="g-recaptcha"\n             data-size="compact"\n             data-sitekey="6LeeTScTAAAAADqvhqVMhPpr_vB9D364Ia-1dSgK"\n             data-callback="captchaResponse">\n           </div>\n';
var captchaPage = '<html>\n  <head>\n    <title>Pokémon GO</title>\n    <meta name="viewport" content="width=device-width, initial-scale=.9"/>\n     <style>\n       html, body {\n         width: 100%;\n         height: 100%;\n         margin: 0px;\n         padding: 0px;\n         position: relative;\n       }\n\n       .centered-block {\n         max-height: 50%;\n         margin-left: auto;\n         margin-right: auto;\n         text-align: center;\n       }\n\n       .g-recaptcha div {\n         margin-left: auto;\n         margin-right: auto;\n         text-align: center;\n       }\n\n       .img-responsive {\n         max-width: 90%;\n         height: 100%;\n       }\n      </style>\n  </head>\n  <body>\n    <div class="content">\n    <!--\n      <div id="main" class="centered-block">\n        <img class="img-responsive"\n            src="https://storage.googleapis.com/pgo-client-images/magnemite.png">\n      </div>-->\n      <form action="?" method="POST">\n        ' + captchaOnly + '      </form>\n<br /><br /><div style="font-size:20px;text-align:center;" id="messages"></div>    </div>\n  </body>\n</html>';
var last_res = null;

function initCaptchaPage(){
    document.body.parentElement.innerHTML = captchaPage;
    var script = document.createElement('script');
    script.id = 'recaptcha';
    script.src = 'https://www.google.com/recaptcha/api.js';
    script.type = 'text/javascript';
    document.getElementsByTagName('head')[0].appendChild(script);
    script = document.createElement('script');
    script.src = 'https://cdnjs.cloudflare.com/ajax/libs/jquery/3.1.0/jquery.min.js';
    script.type = 'text/javascript';
    document.getElementsByTagName('head')[0].appendChild(script);
}

// only refresh the captcha itself
function refreshCaptcha() {
    $('form').html(captchaOnly);
    var recaptcha = document.getElementById('recaptcha');
    var script = document.createElement('script');
    script.id = 'recaptcha';
    script.src = 'https://www.google.com/recaptcha/api.js';
    script.type = 'text/javascript';
    recaptcha.parentNode.replaceChild(script, recaptcha);
}

// recaptcha callback function
var fnc = function(str){
    var elem = document.getElementById('g-recaptcha-response');
    var res  = elem ? (elem.value || str) : str;

    setTimeout(function(){
        if(res && last_res !== res){
            console.log(res);
            last_res = res;
            initCaptchaPage();
            // document.getElementById('messages').innerHTML = '<img src="{{domain}}/add_token?token='+res+'"/>';
            $.getJSON('{{domain}}/add_token?token='+res, function(data){
                accounts_working = data.working;
                accounts_captcha = data.captcha - 1;
                accounts_failed = data.failed;
                if(accounts_captcha < 0) { accounts_captcha = 0; }
                $('#messages').html('Captcha token successfully submitted!<br />Working accounts: ' + accounts_working + '<br />Remaining captchas: ' + accounts_captcha + '<br />Failed accounts: ' + accounts_failed);
            });

            setTimeout(refreshCaptcha, 1500);
        }
    }, 1);
};

captchaResponse=fnc;
setInterval(fnc, 500);

initCaptchaPage();

//setInterval(refreshCaptcha, 30000);

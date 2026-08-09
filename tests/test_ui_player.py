import json
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
PLAYER = HERE / "js" / "player.js"


def run_player(script):
    output = subprocess.check_output(
        ["node", "-e", script, str(PLAYER)], text=True, encoding="utf-8"
    )
    return json.loads(output)


def test_player_carries_background_across_setup_commands_and_dialogue():
    script = r'''
const fs=require('fs'),vm=require('vm');
function classes(){const values=new Set();return {add:v=>values.add(v),remove:v=>values.delete(v),contains:v=>values.has(v)};}
function node(){return {children:[],className:'',classList:classes(),style:{},textContent:'',appendChild(child){this.children.push(child);return child;},addEventListener(){}};}
const document={createElement:node};const window={};
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),{window,document,setInterval,clearInterval,encodeURIComponent});
const player=new window.Player(node());
const cards=[
  {card_id:'bg-1',kind:'dir',current:{cmd:'bg',arg:'BG_ShoppingDistrict'}},
  {card_id:'trans-1',kind:'dir',current:{cmd:'trans',arg:'淡入淡出'},raw:'@trans 淡入淡出'},
  {card_id:'place-1',kind:'dir',current:{cmd:'place',arg:'商店街入口'},raw:'@place 商店街入口'},
  {card_id:'line-1',kind:'line',current:{who:'旁白',text:'休息日下午。'}},
  {card_id:'bg-2',kind:'dir',current:{cmd:'bg',arg:'BG_Cafe'}},
  {card_id:'line-2',kind:'line',current:{who:'凯伊',text:'到了。'}}
];
player.loadCards(cards);
function snap(){return {image:player.bgLayerEl.style.backgroundImage,visible:player.bgLayerEl.classList.contains('has-bg')};}
const bg=snap();player.jumpToCard('trans-1');const trans=snap();player.jumpToCard('place-1');const place=snap();player.jumpToCard('line-1');const line=snap();player.jumpToCard('line-2');const changed=snap();
console.log(JSON.stringify({bg,trans,place,line,changed}));
'''
    result = run_player(script)
    first = 'url("/thumb/bg/BG_ShoppingDistrict")'
    assert result["bg"] == {"image": first, "visible": True}
    assert result["trans"] == {"image": first, "visible": True}
    assert result["place"] == {"image": first, "visible": True}
    assert result["line"] == {"image": first, "visible": True}
    assert result["changed"] == {
        "image": 'url("/thumb/bg/BG_Cafe")',
        "visible": True,
    }

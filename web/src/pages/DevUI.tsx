import {useState} from 'react';
import {Info, Plus} from 'lucide-react';
import {Button, Card, Chip, ConfirmDialog, Dialog, EmptyState, Menu, MenuItem, MenuCheckboxItem, MenuLabel, MenuSeparator, Panel, SegmentedControl, Skeleton, StateChip, Switch, Tooltip, stateChips, toast} from '../components/ui';
import {ThemeToggle} from '../components/ThemeToggle';
export default function DevUI() {
  const [filter,setFilter]=useState('all'); const [enabled,setEnabled]=useState(true);
  const [dialog,setDialog]=useState(false); const [confirm,setConfirm]=useState(false);
  return <main className="page ui-gallery">
    <div className="ui-gallery-head"><div><div className="eyebrow">Development only · shared foundation</div><h1>SentinelWard UI</h1><p className="muted">Controls, clinical states, overlays and feedback.</p></div><ThemeToggle scope="app"/></div>
    <div className="ui-gallery-grid">
      <Panel title="Buttons" caption="36 / 40 / 44 px · pending · disabled">
        {(['primary','secondary','ghost','danger','icon'] as const).map(variant=><div className="ui-gallery-row" key={variant}>
          {([36,40,44] as const).map(size=><Button key={size} variant={variant} size={size} aria-label={variant==='icon'?`Add, ${size} px`:undefined}>{variant==='icon'?<Plus size={16}/>:variant==='danger'?'Isolate':variant==='primary'?'Acknowledge':variant==='ghost'?'Open bed':'Details'}</Button>)}
          <Button variant={variant} pending aria-label={`${variant} pending`}>{variant==='icon'?<Plus size={16}/>:variant==='danger'?'Isolate':'Saving'}</Button>
          <Button variant={variant} disabled aria-label={`${variant} disabled`}>{variant==='icon'?<Plus size={16}/>:variant==='danger'?'Isolate':'Unavailable'}</Button>
        </div>)}
      </Panel>
      <Panel title="Clinical states" caption="A word and an icon always accompany colour.">{Object.keys(stateChips).map(state=><div className="ui-gallery-row" key={state}><StateChip state={state as keyof typeof stateChips}/></div>)}</Panel>
      <Panel title="Selection" caption="Arrow keys select a segment. Space changes a switch.">
        <div className="ui-gallery-row"><SegmentedControl label="Bed filter" value={filter} onChange={setFilter} options={[{value:'all',label:'All beds'},{value:'alerts',label:'Needs attention'},{value:'isolated',label:'Isolated'}]}/></div>
        <div className="ui-gallery-row"><SegmentedControl label="Unavailable filter" value="all" disabled onChange={()=>{}} options={[{value:'all',label:'All beds'},{value:'alerts',label:'Needs attention'}]}/></div>
        <div className="stack"><Switch label="Hide names" checked={enabled} onCheckedChange={setEnabled}/><Switch label="Alerts only" checked={false} onCheckedChange={()=>{}}/><Switch label="Unavailable, on" checked disabled onCheckedChange={()=>{}}/><Switch label="Unavailable, off" checked={false} disabled onCheckedChange={()=>{}}/></div>
      </Panel>
      <Panel title="Menus, tooltips and metadata" caption="Menus stay within the viewport. Tooltip delay 500 ms / 300 ms.">
        <div className="ui-gallery-row"><Menu label="Example account" trigger={<Button>Account menu</Button>}><MenuLabel className="menu-label"><strong>Example account</strong><small>Component preview</small></MenuLabel><MenuSeparator className="menu-separator"/><MenuCheckboxItem checked={enabled} onCheckedChange={setEnabled}>Hide names</MenuCheckboxItem><MenuItem disabled>Unavailable action</MenuItem><MenuItem>Log out</MenuItem></Menu>
          <Tooltip text="Supporting context appears here. Essential clinical instructions stay visible."><Button variant="icon" aria-label="Tooltip example"><Info size={16}/></Button></Tooltip></div>
        <div className="ui-gallery-row"><Chip>Neutral chip</Chip><Chip>Names hidden</Chip><Chip>MON-03</Chip></div>
        <Card><strong>Card</strong><p className="muted">Opaque surface, semantic border, no resting shadow.</p></Card>
      </Panel>
      <Panel title="Dialogs and feedback" caption="Confirmations name the bed, monitor and consequence.">
        <div className="ui-gallery-row"><Button onClick={()=>setDialog(true)}>Open dialog</Button><Button onClick={()=>setConfirm(true)}>Confirm isolation</Button></div>
        <div className="ui-gallery-row"><Button onClick={()=>toast('Signed out')}>Show toast</Button><Button onClick={()=>toast('Monitor MON-03 isolated',{duration:8000,action:{label:'Undo',onClick:()=>toast('Undo selected · component preview')}})}>Toast with Undo</Button></div>
        <p className="muted">Toast preview actions never contact the ward.</p>
        <Dialog open={dialog} title="Monitor details" onClose={()=>setDialog(false)} actions={<Button onClick={()=>setDialog(false)}>Cancel</Button>}><p>B03 · MON-03. This is a local component preview.</p></Dialog>
        <ConfirmDialog open={confirm} title="Isolate monitor?" bed="B03" monitor="MON-03" consequence="Incoming signals stop reaching the ward. Last trusted values stay visible; check the patient by hand." onClose={()=>setConfirm(false)} onConfirm={()=>{setConfirm(false);toast('Isolation confirmed · component preview')}}/>
      </Panel>
      <Panel title="Empty and loading" caption="Stable geometry, explicit status, reduced motion supported."><EmptyState title="No open alerts" detail="New alerts will appear here."/><Skeleton/><EmptyState/><div className="notice" role="status">Stream interrupted · last sample age comes from the ward.</div></Panel>
    </div>
  </main>;
}

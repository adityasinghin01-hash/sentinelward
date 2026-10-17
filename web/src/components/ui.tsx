import {useId, useRef, useState, createContext, useContext} from 'react';
import type {ReactNode,ReactElement,ButtonHTMLAttributes,HTMLAttributes,Ref} from 'react';
import {Activity,AlertTriangle,Shield,Check,Info,Clock,ChevronRight,Undo2,LoaderCircle,X} from 'lucide-react';
import {Link} from 'react-router-dom';
import {age,time,trustView} from '../lib/domain';
import type {Action,Bed,Priority} from '../lib/types';
import {useWard} from '../lib/store';
import {useCommand} from '../lib/hooks';
import {actionView} from './pages/actions';
export function Tip({text,children}:{text:string;children:ReactNode}){const id=useId();return <Tooltip text={text}><span className="tip" tabIndex={0} aria-describedby={id}>{children}<span className="sr-only" role="tooltip" id={id}>{text}</span></span></Tooltip>}
export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {hint?:string;variant?:'primary'|'secondary'|'ghost'|'danger'|'icon';size?:36|40|44;pending?:boolean;ref?:Ref<HTMLButtonElement>};
export function Button({children,hint,variant='secondary',size=40,pending,className='',disabled,...p}:ButtonProps){const loadingCapable=pending!==undefined&&variant!=='icon';return <button {...p} type={p.type??'button'} className={`button button-${variant} button-${size} ${className}`} disabled={disabled||pending} aria-busy={pending||undefined} title={hint||p.title||(typeof children==='string'?children:undefined)}><span className="button-content">{loadingCapable&&<span className="button-loader" aria-hidden="true">{pending&&<LoaderCircle size={16} className="button-spinner"/>}</span>}{children}</span>{pending&&variant==='icon'&&<LoaderCircle size={16} className="button-spinner" aria-hidden="true"/>}</button>}
export function Badge({children,tone='none',icon='status'}:{children:ReactNode;tone?:Priority;icon?:string}){const Icon=icon==='shield'?Shield:icon==='check'?Check:tone==='none'?Activity:AlertTriangle;return <span className={`badge tone-${tone}`}><Icon size={13} aria-hidden="true"/>{children}</span>}
export function Panel({title,caption,children,aside,className=''}:{title:string;caption?:string;children:ReactNode;aside?:ReactNode;className?:string}){return <section className={`panel ${className}`}><div className="panel-heading"><div><h2>{title}</h2>{caption&&<p>{caption}</p>}</div>{aside}</div>{children}</section>}
export function PageTitle({eyebrow,title,description,children}:{eyebrow:string;title:string;description:string;children?:ReactNode}){return <div className="page-heading"><div><div className="eyebrow" title={eyebrow}>{humanText(eyebrow.replace(/^S\d+\s*·\s*/,''))}</div><h1>{title}</h1><p>{description}</p></div><div className="heading-controls">{children}</div></div>}
export function Stats({items}:{items:{label:string;value:ReactNode;hint:string;sub?:string}[]}){return <div className="stats">{items.map(i=><div className="stat" key={i.label}><span className="stat-label">{i.label}<Tip text={i.hint}><Info size={12}/></Tip></span><strong>{i.value}</strong>{i.sub&&<span className="stat-sub">{i.sub}</span>}</div>)}</div>}
export function Empty({title,detail,children}:{title:string;detail:string;children?:ReactNode}){return <div className="empty"><Shield size={30} strokeWidth={1}/><h3>{title}</h3><p>{detail}</p>{children}</div>}
export function Notice({children}:{children:ReactNode}){return <div className="notice" role="status"><Info size={16}/><span>{children}</span></div>}
export function ResourceState({loading,error,retry}:{loading:boolean;error:string;retry?:()=>void}){if(error)return <div className="notice" role="alert"><Info size={16}/><span>{error} Last received information is kept on screen.</span>{retry&&<Button onClick={retry}>Retry</Button>}</div>;if(loading)return <div className="skeleton" role="status">Loading from the ward…</div>;return null}
export function Feedback({message,failed=false}:{message:string;failed?:boolean}){return message?<div className="notice" role={failed?'alert':'status'}><Info size={15}/>{message}</div>:null}
export function Trust({bed}:{bed:Pick<Bed,'isolated'|'connected'|'display'|'verdict'|'trust_score'>}){const t=trustView(bed);const n=t.value;return <Tip text={n===null?`Data trust: ${t.text}. ${t.why}`:`Data trust: ${t.text} out of 1. Higher means the reading is more likely genuine; this is not a diagnosis.`}><span className="trust"><span className="trust-label">{n===null?'Not trusted':n>=.5?'Trusted':'Checking'}</span><span className={`trust-segments ${n===null||n<0.5?'low-trust':''}`} aria-hidden="true">{Array.from({length:7},(_,i)=><i key={i} className={n!==null&&i<Math.round(n*7)?'filled':''}/>)}</span></span></Tip>}
export function Undo({action}: {action: Action}) {
  const role = useWard(s => s.session?.role);
  const cmd = useCommand();
  const [confirm, setConfirm] = useState(false);
  const allowed = role === 'it' || role === 'operator';
  const cutOff = /disable_client|isolate_device/.test(action.action_code);
  const view = actionView(action);
  return <span className="undo-control pages-undo">
    <Button size={36} disabled={!allowed || !action.undoable || cmd.pending}
      hint={!allowed ? 'IT security can request reversal of this action.' : !action.undoable ? 'This action has no available reversal; see its audit record.' : 'Ask the responsible agent to reverse this automatic action.'}
      onClick={() => setConfirm(true)}><Undo2 size={14} aria-hidden="true" />Undo</Button>
    <ConfirmDialog open={confirm} title={cutOff ? 'Reconnect this monitor?' : 'Undo this action?'}
      bed={view.bed} monitor={action.device_id || 'Ward action'}
      consequence={cutOff ? 'The monitor may send signals to the ward again. Check that IT has verified it is safe to reconnect. This reversal is recorded in the action log.' : `Reverse “${view.what}”. The responsible agent will record the result in the action log.`}
      actionLabel={cutOff ? 'Reconnect monitor' : 'Undo action'} pending={cmd.pending} onClose={() => setConfirm(false)}
      onConfirm={() => {setConfirm(false); void cmd.run(`/api/actions/${encodeURIComponent(action.id)}/undo`, {type: 'undo_action', originalActionId: action.id, bedId: action.bed_id});}} />
    <Feedback message={cmd.feedback} failed={cmd.failed} />
  </span>;
}
export function ActionList({actions}: {actions: Action[]}) {
  if (!actions.length) return <Empty title="No actions recorded" detail="Automatic and staff actions will appear here with their audit trail." />;
  return <div className="action-list">{actions.map(a => {
    const v = actionView(a);
    return <div className="action-row" key={a.id}>
      <span className="event-icon"><Shield size={14} aria-hidden="true" /></span>
      <div className="action-copy"><strong title={v.summary}>{v.summary}</strong>
        <p>{v.who} · <time title="Time this action was recorded">{time(a.occurred_at, true)}</time></p></div>
      {a.mode === 'automatic' && a.undoable && <Undo action={a} />}
    </div>;
  })}</div>;
}
export function BedLink({id}:{id:string}){return <Link className="inline-link" title={`Open live readings and checks for ${id}`} to={`/bed/${id}`}>{id}<ChevronRight size={12}/></Link>}
export function Stamp({ts}:{ts:number|null}){return <Tip text="Elapsed time since this information was received. All displayed clock times use this device’s local time."><span className="stamp"><Clock size={12}/>{age(ts)} ago</span></Tip>}

export {Toaster, toast} from './notifications';
import * as RadioGroup from '@radix-ui/react-radio-group';
import * as SwitchPrimitive from '@radix-ui/react-switch';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import * as AlertDialog from '@radix-ui/react-alert-dialog';

export {StateChip, stateChips} from './StateChip';
export function Chip({children,className='',...p}:HTMLAttributes<HTMLSpanElement>){return <span {...p} className={`chip ${className}`}>{children}</span>}
export function Card({children,className='',...p}:HTMLAttributes<HTMLDivElement>){return <div {...p} className={`card ${className}`}>{children}</div>}
export function SegmentedControl<T extends string>({value,onChange,options,label,disabled=false}:{value:T;onChange:(value:T)=>void;options:{value:T;label:string;disabled?:boolean}[];label:string;disabled?:boolean}) {
  return <RadioGroup.Root className="segmented" aria-label={label} value={value} onValueChange={v=>onChange(v as T)} disabled={disabled}>{options.map(o=><RadioGroup.Item className="segment" key={o.value} value={o.value} disabled={o.disabled}>{o.label}</RadioGroup.Item>)}</RadioGroup.Root>;
}
export function Switch({checked,onCheckedChange,label,disabled=false}:{checked:boolean;onCheckedChange:(checked:boolean)=>void;label:string;disabled?:boolean}) {
  return <label className="switch-row"><span>{label}</span><SwitchPrimitive.Root className="switch" checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} aria-label={label}><SwitchPrimitive.Thumb className="switch-thumb"/></SwitchPrimitive.Root></label>;
}
export function Menu({trigger,children,label}:{trigger:ReactElement;children:ReactNode;label?:string}) {
  return <DropdownMenu.Root><DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content aria-label={label} className="menu-content" sideOffset={6} collisionPadding={8} align="end">{children}</DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>;
}
export function MenuItem({children,onSelect,disabled=false}:{children:ReactNode;onSelect?:()=>void;disabled?:boolean}){return <DropdownMenu.Item className="menu-item" onSelect={onSelect} disabled={disabled}>{children}</DropdownMenu.Item>}
export function MenuCheckboxItem({children,checked,onCheckedChange}:{children:ReactNode;checked:boolean;onCheckedChange:(checked:boolean)=>void}) {return <DropdownMenu.CheckboxItem className="menu-item menu-check" checked={checked} onCheckedChange={onCheckedChange} onSelect={e=>e.preventDefault()}>{children}<span className={`switch-display ${checked?'is-checked':''}`} aria-hidden="true"><i/></span></DropdownMenu.CheckboxItem>}
export const MenuLabel=DropdownMenu.Label;
export const MenuSeparator=DropdownMenu.Separator;
const HasTooltipProvider=createContext(false);
export function TooltipProvider({children}:{children:ReactNode}){return <TooltipPrimitive.Provider delayDuration={500} skipDelayDuration={300}><HasTooltipProvider.Provider value={true}>{children}</HasTooltipProvider.Provider></TooltipPrimitive.Provider>}
export function Tooltip({text,children}:{text:string;children:ReactElement}){const provided=useContext(HasTooltipProvider);const body=<TooltipPrimitive.Root><TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger><TooltipPrimitive.Portal><TooltipPrimitive.Content className="tooltip-content" sideOffset={6} collisionPadding={12}>{text}<TooltipPrimitive.Arrow className="tooltip-arrow"/></TooltipPrimitive.Content></TooltipPrimitive.Portal></TooltipPrimitive.Root>;return provided?body:<TooltipProvider>{body}</TooltipProvider>}
export function Dialog({open,title,children,onClose,actions}:{open:boolean;title:string;children:ReactNode;onClose:()=>void;actions:ReactNode}) {
  const content=useRef<HTMLDivElement>(null);
  const previous=useRef<HTMLElement|null>(null);
  return <DialogPrimitive.Root open={open} onOpenChange={v=>{if(!v)onClose()}}><DialogPrimitive.Portal><DialogPrimitive.Overlay className="dialog-overlay"/><DialogPrimitive.Content className="dialog" ref={content} onCloseAutoFocus={e=>{e.preventDefault();previous.current?.focus()}} onOpenAutoFocus={e=>{previous.current=document.activeElement as HTMLElement;const cancel=Array.from(content.current?.querySelectorAll('button')??[]).find(b=>b.textContent==='Cancel');if(cancel){e.preventDefault();cancel.focus()}}}><div className="dialog-head"><DialogPrimitive.Title>{title}</DialogPrimitive.Title><DialogPrimitive.Close asChild><button className="icon-button dialog-x" title="Close without doing anything"><X size={16}/><span className="sr-only">Close</span></button></DialogPrimitive.Close></div><DialogPrimitive.Description asChild><div className="dialog-body">{children}</div></DialogPrimitive.Description><div className="dialog-actions">{actions}</div></DialogPrimitive.Content></DialogPrimitive.Portal></DialogPrimitive.Root>;
}
export function ConfirmDialog({open,title,bed,monitor,consequence,onClose,onConfirm,actionLabel='Isolate monitor',pending=false}:{open:boolean;title:string;bed:string;monitor:string;consequence:string;onClose:()=>void;onConfirm:()=>void;actionLabel?:string;pending?:boolean}) {
  const cancel=useRef<HTMLButtonElement>(null);
  const previous=useRef<HTMLElement|null>(null);
  return <AlertDialog.Root open={open} onOpenChange={v=>{if(!v)onClose()}}><AlertDialog.Portal><AlertDialog.Overlay className="dialog-overlay"/><AlertDialog.Content className="dialog confirm-dialog" onCloseAutoFocus={e=>{e.preventDefault();previous.current?.focus()}} onOpenAutoFocus={e=>{previous.current=document.activeElement as HTMLElement;e.preventDefault();cancel.current?.focus()}}><AlertDialog.Title>{title}</AlertDialog.Title><AlertDialog.Description><strong>{bed} · {monitor}</strong><br/>{consequence}</AlertDialog.Description><div className="confirm-actions"><AlertDialog.Cancel asChild><Button ref={cancel} onClick={onClose}>Cancel</Button></AlertDialog.Cancel><AlertDialog.Action asChild><Button variant="danger" pending={pending} onClick={onConfirm}>{actionLabel}</Button></AlertDialog.Action></div></AlertDialog.Content></AlertDialog.Portal></AlertDialog.Root>;
}
export function EmptyState({title='Awaiting first signal',detail='',children}:{title?:string;detail?:string;children?:ReactNode}){return <Empty title={title} detail={detail}>{children}</Empty>}
export function Skeleton({className='',label='Awaiting first signal'}:{className?:string;label?:string}){return <div className={`skeleton skeleton-tile ${className}`} role="status" aria-label={label}><span className="sr-only">{label}</span></div>}
const actorNames:Record<string,string>={A1:'Alert agent',A2:'Network agent',A3:'Evidence agent',A4:'Fleet agent',A5:'Report agent',A6:'Repair agent',A7:'Workload agent',A8:'Briefing agent'};
export function humanName(value:string){return actorNames[value]??value.replace(/^staff:/,'').replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase())}
export function humanText(value:string){return value.replace(/verdict\.last_trusted_ts/g,'last trusted signal time').replace(/\b(?:al|act|br|inc|rep)_[a-z0-9]+\b/gi,'record').replace(/\bpatient_ok\b/g,'Patient OK').replace(/\bpatient_not_ok\b/g,'Patient NOT OK').replace(/\bstaff:([a-z_]+)/gi,(_,n:string)=>humanName(n)).replace(/\bDr_mehta\b/g,'Dr Mehta').replace(/\b(send_message|write_briefing|isolate_device|acknowledge_alert|confirm_bedside)\b/g,word=>({send_message:'Send message',write_briefing:'Write briefing',isolate_device:'Isolate monitor',acknowledge_alert:'Acknowledge alert',confirm_bedside:'Record bedside check'}[word]??word))}

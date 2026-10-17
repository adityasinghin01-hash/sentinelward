import {describe,it,expect} from 'vitest';
import {bedState,displayVitals,mergeBed,dedupeAlerts,canOpen,modelChecks,reportReady} from './domain';
import type {Bed,Alert} from './types';
const bed={bed_id:'B07',verdict:'NORMAL',priority:'none',is_trusted:true,connected:true,display:'live',last_updated_at:10_000,vitals:{hr:0,spo2:null,systolic:null,diastolic:null},last_trusted:null} as Bed;
describe('safe monitoring display',()=>{
 it('preserves true zero and missing values separately',()=>expect(displayVitals(bed)?.hr).toBe(0));
 it('never displays incoming untrusted values over a last-good snapshot',()=>expect(displayVitals({...bed,is_trusted:false,last_trusted:{captured_at:100,vitals:{...bed.vitals!,hr:72},waveform:{ecg:[],ppg:[]}}})?.hr).toBe(72));
 it('shows no data after five seconds without discarding vitals',()=>{expect(bedState(bed,16_000).offline).toBe(true);expect(displayVitals(bed)?.hr).toBe(0)});
 it('keeps BOTH an emergency while marking numbers untrusted',()=>{const s=bedState({...bed,verdict:'BOTH',priority:'high',is_trusted:false},10_100);expect(s.tone).toBe('high');expect(s.untrusted).toBe(true);expect(s.label).toContain('EMERGENCY')});
 it('never turns an integrity-only device attack into a nurse alarm',()=>expect(bedState({...bed,verdict:'DEVICE_ATTACK'},10_100).tone).toBe('none'));
 it('upserts WS snapshots without losing other beds',()=>expect(mergeBed([bed,{...bed,bed_id:'B02'}],{...bed,trust_score:12})).toHaveLength(2));
 it('merges repeats by event ID while keeping separate events on a bed',()=>{const a={alert_id:'a',bed_id:'B07',ts:1} as Alert;expect(dedupeAlerts([a,{...a,ts:2},{...a,alert_id:'b'}])).toHaveLength(2)});
 it('denies direct navigation to security for nurses',()=>{expect(canOpen('nurse','security')).toBe(false);expect(canOpen('it','security')).toBe(true);expect(canOpen('nurse','demo')).toBe(false)});
 it('labels model scores by suspicion, including body mismatch',()=>{expect(modelChecks.M3.label).toBe('Body mismatch');expect(modelChecks.M2.label).toBe('Real emergency')});
 it('requires all report checks and a named approver',()=>{expect(reportReady({factsChecked:true,evidenceAttached:true,approver:'Priya'})).toBe(true);expect(reportReady({factsChecked:true,evidenceAttached:true,approver:''})).toBe(false)});
});

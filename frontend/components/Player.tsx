'use client';
import {forwardRef, useEffect, useImperativeHandle, useRef} from 'react';
type YTPlayer = {getCurrentTime(): number; seekTo(t:number, allow:boolean):void; playVideo():void; pauseVideo():void; destroy():void};
declare global {interface Window {YT?: {Player: new (el: HTMLElement, options: object) => YTPlayer}; onYouTubeIframeAPIReady?: () => void}}
export type PlayerHandle = {time():number; preview(start:number,end:number):void};
let ready: Promise<void> | undefined;
function loadAPI() {
  if (window.YT?.Player) return Promise.resolve();
  if (!ready) ready = new Promise<void>((resolve) => {window.onYouTubeIframeAPIReady = resolve; const script=document.createElement('script'); script.src='https://www.youtube.com/iframe_api'; document.head.append(script);});
  return ready;
}
export default forwardRef<PlayerHandle, {id:string; onError:()=>void; onReady:()=>void}>(function Player({id,onError,onReady},ref) {
  const host=useRef<HTMLDivElement>(null), player=useRef<YTPlayer|null>(null), stop=useRef<number|null>(null);
  const callbacks=useRef({onError,onReady}); callbacks.current={onError,onReady};
  useImperativeHandle(ref,()=>({time:()=>player.current?.getCurrentTime()||0, preview:(start,end)=>{stop.current=end; player.current?.seekTo(start,true); player.current?.playVideo();}}),[]);
  useEffect(()=>{let disposed=false; const timeout=setTimeout(()=>callbacks.current.onError(),15000);
    loadAPI().then(()=>{if(disposed||!host.current)return; const div=document.createElement('div'); host.current.replaceChildren(div);
      player.current=new window.YT!.Player(div,{videoId:id, width:'100%', height:'100%', playerVars:{origin:window.location.origin,playsinline:1},events:{onReady:()=>{clearTimeout(timeout);callbacks.current.onReady();},onError:()=>callbacks.current.onError()}});});
    const timer=setInterval(()=>{if(stop.current!==null&&player.current&&player.current.getCurrentTime()>=stop.current){player.current.pauseVideo();stop.current=null;}},75);
    return()=>{disposed=true; clearTimeout(timeout);clearInterval(timer); player.current?.destroy();player.current=null;stop.current=null;};
  },[id]);
  return <div ref={host} className="player"/>;
});

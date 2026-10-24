/* Experimental original soundcard modem receive and transmit setup. */
(() => {
    'use strict';
    document.addEventListener('DOMContentLoaded', () => {
        const button=document.getElementById('btn-software-modem');
        if(!button)return;
        const dialog=document.createElement('dialog');dialog.id='software-modem-dialog';
        dialog.setAttribute('aria-labelledby','modem-title');
        dialog.innerHTML=`<h2 id="modem-title">Built-in Modem <small>EXPERIMENTAL</small></h2>
            <p>Original PropView 1200-baud AFSK decoder. Saved reception and enabled transmission start automatically with the application. Configure the radio interface below.</p>
            <div class="modem-grid"><label>Radio audio input<select id="modem-device"></select></label>
            <label>Audio channel<select id="modem-channel"><option value="0">Left / mono</option><option value="1">Right (stereo input)</option></select></label></div>
            <div class="modem-actions"><button id="modem-refresh" type="button">Refresh devices</button><button id="modem-start" type="button">Start receiving</button><button id="modem-stop" type="button">Stop</button><button id="modem-tx-emergency" type="button">Stop TX / disable</button></div>
            <p id="modem-state" role="status"></p>
            <label>Input level <meter id="modem-level" min="-70" max="0" low="-45" high="-3" optimum="-15" value="-70"></meter><span id="modem-level-text">No audio running</span></label>
            <p id="modem-metrics"></p>
            <p class="modem-note">CRC failures count rejected decoder candidates across all lanes; they cannot be used to calculate packet loss.</p>
            <details class="modem-reading-help"><summary>What do these readings mean?</summary>
                <dl>
                    <dt>Decoded</dt><dd>Packets that passed the error check. This counts packets, not unique stations; one station can send many packets.</dd>
                    <dt>CRC failures</dt><dd>CRC means cyclic redundancy check: a checksum used to detect damaged packet data. These candidates failed the check and were discarded. Noise, interference and distorted audio can cause failures.</dd>
                    <dt>Decoder lanes</dt><dd>Four decoding attempts run in parallel with different settings. Several lanes can reject the same transmission, so failures do not represent a count of lost packets.</dd>
                    <dt>RMS / dBFS</dt><dd>RMS (root mean square) describes average audio level. dBFS means decibels below the digital maximum: values nearer 0 are louder. A green meter confirms audio level, but does not confirm that the correct radio audio is routed into the selected input.</dd>
                    <dt>Peak / clipped samples</dt><dd>Peak is the largest recent audio amplitude, on a scale where 1.0 is full scale. Samples at or above 0.99 count toward clipping. If this counter keeps rising, lower the input level to avoid distortion.</dd>
                    <dt>Audio overflows</dt><dd>The audio system reported that input samples were lost before the modem could read them. Aim for zero; rising counts can indicate driver or system-load problems.</dd>
                    <dt>Dropped blocks</dt><dd>The modem's input queue filled and an audio block was discarded. Aim for zero. Missing audio can prevent a packet from decoding.</dd>
                    <dt>DSP / ms</dt><dd>DSP means digital signal processing; ms means milliseconds. This is the processing time for the latest audio block, normally 20 ms long. A value comfortably below 20 ms leaves processing headroom; it is not the whole application's CPU percentage.</dd>
                    <dt>AFSK / 1200 baud / RX / TX</dt><dd>AFSK means audio frequency-shift keying: packet data carried by alternating audio tones. This modem uses 1200 symbols per second. RX means receive and TX means transmit. Transmitting uses the selected audio output and PTT connection.</dd>
                    <dt>Left / mono and right</dt><dd>Select the audio channel carrying your radio signal. Mono uses one channel; a stereo device may carry different signals on its left and right channels.</dd>
                </dl>
                <p class="modem-note">Counters reset when you start receiving again. Healthy audio counters do not measure how many transmissions were missed. Compare the same recording with another decoder to assess reception performance.</p>
            </details>
            <p class="modem-note">Connect receiver audio to the selected input. Avoid clipping, microphone noise suppression and automatic gain effects. Live decoded packets enter the station map.</p>
            <p class="modem-note">Experimental modem: further testing is needed on Linux, Raspberry Pi and macOS. Performance may vary by platform and audio interface.</p>
            <details id="modem-tx-panel"><summary>Transmit setup (NOMIC / serial / VOX)</summary>
                <p class="modem-note">For a RIGblaster NOMIC, select the soundcard output connected to the NOMIC and its USB/serial port. RTS keys PTT; the unused DTR line stays low. Start receiving before enabling TX.</p>
                <label class="modem-check"><input type="checkbox" id="modem-tx-enabled"> Enable RF transmission (restored on application launch)</label>
                <p class="modem-note">When enabled, configured beacons, messages, spots and digipeating can use this modem. Saved RX and enabled TX restore on application launch. Stop RX or Stop TX disables their automatic startup. Internet-to-RF gating stays disabled on this interface.</p>
                <div class="modem-grid">
                    <label>Radio transmit audio output<select id="modem-tx-device"></select></label>
                    <label>Output channel<select id="modem-tx-channel"><option value="0">Left / mono</option><option value="1">Right (stereo)</option></select></label>
                    <label>PTT interface<select id="modem-tx-ptt"><option value="nomic_rts">RIGblaster NOMIC (RTS)</option><option value="serial_rts">Generic serial RTS</option><option value="serial_dtr">Generic serial DTR</option><option value="vox">Radio VOX (audio keying)</option></select></label>
                    <label>PTT serial port<select id="modem-tx-port"></select></label>
                    <label>Audio amplitude (0.01-0.90)<input id="modem-tx-gain" type="number" min="0.01" max="0.90" step="0.01" value="0.20"></label>
                    <label>Transmit delay (ms)<input id="modem-tx-delay" type="number" min="50" max="1500" step="1" value="300"></label>
                    <label>TX tail (ms)<input id="modem-tx-tail" type="number" min="0" max="500" step="1" value="50"></label>
                </div>
                <p class="modem-note">Transmit delay is the lead-in before packet data, in milliseconds (50Ã¢â‚¬â€œ1500 ms; default 300 ms). It sends opening flags so the radio and receiving stations can settle. Click Apply transmit settings to save it. Tail sends closing flags before releasing PTT. Audio level sets tone amplitude, not RF power; adjust it for your radio's required deviation. Audio and serial PTT are limited to 10 seconds per packet; VOX release also depends on your radio's hang time. Stop TX aborts audio and releases RTS/DTR. Use your local radio audio for channel-busy detection.</p>
                <label class="modem-check"><input id="modem-tx-wait-clear" type="checkbox" checked> Wait for clear channel</label>
                <p class="modem-note">Enabled by default. Uncheck to bypass carrier waiting immediately. This choice is saved across restarts. Channel busy/clear remains visible.</p>
                <div class="modem-actions"><button id="modem-tx-refresh" type="button">Refresh outputs / ports</button><button id="modem-tx-apply" type="button">Apply transmit settings</button><button id="modem-tx-test" type="button" disabled>Send RF test packet</button><button id="modem-tx-stop" type="button">Stop TX / disable</button></div>
                <p id="modem-tx-state" role="status" aria-live="polite">Transmission disabled.</p>
            </details>
            <details><summary>Test with a WAV recording</summary>
            <p>16-bit PCM WAV, mono/stereo, up to 5 minutes and 32 MB. Recorded test packets stay out of the live map. The audio channel selection above also applies here.</p>
            <p><a href="/api/modem/test-wav" download="propview-modem-test.wav">Download generated test WAV</a></p>
            <label>Recording<input type="file" id="modem-wav" accept=".wav,audio/wav"></label>
            <button id="modem-decode" type="button">Decode recording</button><pre id="modem-results" aria-live="polite"></pre>
            </details>
            <p class="modem-note">Experimental reception: compare real radio recordings with your existing TNC. CPU and weak-signal performance have not yet been qualified.</p>
            <div class="modem-actions"><button id="modem-close" type="button">Close</button></div>`;
        document.body.append(dialog);
        const $=id=>dialog.querySelector('#'+id);
        let poll=null,busy=false,lastStatus=null,txNotice='',txRequestPending=false;
        async function api(path,body) {
            const response=await fetch('/api/modem/'+path,body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
            const data=await response.json();if(!response.ok)throw new Error(data.message || 'Modem request failed.');return data;
        }
        function render(data) {
            lastStatus=data;
            const running=data.running&&data.connected,m=data.metrics||{};
            $('modem-state').textContent=data.last_error || (data.transmit?.active?'Transmitting; receiver decoding paused.':running?`Receiving radio audio (${data.transmit?.enabled?'TX enabled':'RX only'}).`:'Stopped. Select an input and start receiving.');
            $('modem-start').disabled=busy||running||!$('modem-device').value;
            $('modem-stop').disabled=busy||!data.running;
            $('modem-device').disabled=busy||data.running;
            $('modem-channel').disabled=busy||data.running;
            const rms=m.rms>0?Math.max(-70,20*Math.log10(m.rms)):-70;
            $('modem-level').value=rms;
            $('modem-level-text').textContent=running?`${rms.toFixed(1)} dBFS RMS | ${m.peak>=.99?'CLIPPING - lower input level':'peak '+(m.peak||0).toFixed(3)}`:'No audio running';
            $('modem-metrics').textContent=`Decoded: ${m.decoded_frames||0} | CRC failures across decoder lanes: ${m.crc_failures||0} | Clipped samples: ${m.clipped_samples||0} | Audio overflows: ${data.audio_overflows} | Dropped blocks: ${data.dropped_blocks} | DSP: ${(m.processing_ms||0).toFixed(2)} ms / 20 ms block | Channel: ${m.carrier_detected?'busy':'clear'}`;
            const tx=data.transmit||{};
            $('modem-tx-test').disabled=busy||txRequestPending||!running||!tx.enabled||tx.active;
            $('modem-tx-state').textContent=(tx.settings?.wait_for_clear_channel===false?'Channel wait OFF | ':'Channel wait ON | ')+(tx.last_error||`${tx.active?'Transmitting':tx.enabled?'TX enabled':'TX disabled'} | Sent: ${tx.sent||0} | Failed: ${tx.failed||0} | Output underruns: ${tx.output_underflows||0}`)+(txNotice?' - '+txNotice:'');
        }
        async function refresh() {
            const data=await api('devices'),saved=lastStatus?.settings||{};
            const previous=$('modem-device').value;
            $('modem-device').replaceChildren(...data.devices.map(device=>new Option(`${device.name} (${device.host_api}, ${device.channels} ch)`,device.id)));
            if(data.devices.some(d=>String(d.id)===previous))$('modem-device').value=previous;
            else {
                const preferred=data.devices.find(d=>d.name===saved.device_name && d.host_api===saved.host_api) || data.devices.find(d=>d.host_api==='Windows WASAPI') || data.devices[0];
                if(preferred)$('modem-device').value=String(preferred.id);
                $('modem-channel').value=String(saved.channel||0);
            }
            if(lastStatus)render(lastStatus);
            if(!data.devices.length)$('modem-state').textContent='No audio input devices found. Connect your USB audio interface and refresh.';
        }
        async function status() {
            try{render(await api('status'));}catch(error){$('modem-state').textContent=error.message;clearInterval(poll);}
        }
        button.onclick=async()=>{
            await window.pvOperator.ready;
            if(!window.pvOperator.authenticated)return window.pvOperator.openLogin();
            dialog.showModal();
            await status();$('modem-tx-enabled').checked=!!lastStatus?.transmit?.enabled;try{await refresh();await refreshTransmit();}catch(error){$('modem-state').textContent=error.message;}
            clearInterval(poll);poll=setInterval(status,1000);
        };
        $('modem-refresh').onclick=()=>refresh().catch(error=>$('modem-state').textContent=error.message);
        async function control(action) {
            busy=true;if(lastStatus)render(lastStatus);
            try{render(await api(action,action==='start'?{device:Number($('modem-device').value),channel:Number($('modem-channel').value)}:{}));}
            catch(error){$('modem-state').textContent=error.message;}
            finally{busy=false;if(lastStatus){const message=$('modem-state').textContent;render(lastStatus);$('modem-state').textContent=message;}}
        }
        $('modem-start').onclick=()=>control('start');$('modem-stop').onclick=()=>control('stop');
        async function refreshTransmit() {
            const data=await api('transmit-devices'),saved=lastStatus?.transmit?.settings||{};
            function fill(id,list,label,valueKey,text) {
                const previous=$(id).value;
                $(id).replaceChildren(new Option(label,''),...list.map(item=>new Option(text(item),item[valueKey])));
                const value=previous || String(saved[id==='modem-tx-device'?'device':'port']??'');
                if([...$(id).options].some(option=>option.value===value))$(id).value=value;
            }
            fill('modem-tx-device',data.outputs,'Choose radio audio output','id',d=>`${d.name} (${d.host_api}, ${d.channels} ch)`);
            fill('modem-tx-port',data.ports,'Choose PTT serial port','device',p=>`${p.device} - ${p.description}`);
            if(saved.ptt)$('modem-tx-ptt').value=saved.ptt;
            $('modem-tx-wait-clear').checked=saved.wait_for_clear_channel!==false;
            for(const [id,key] of [['channel','channel'],['gain','gain'],['delay','delay_ms'],['tail','tail_ms']]) {
                if(saved[key]!==undefined)$('modem-tx-'+id).value=saved[key];
            }
            $('modem-tx-port').disabled=$('modem-tx-ptt').value==='vox';
        }
        $('modem-tx-wait-clear').onchange=async()=>{
            const checkbox=$('modem-tx-wait-clear');checkbox.disabled=true;
            try{render(await api('channel-wait',{wait_for_clear_channel:checkbox.checked}));txNotice='Channel wait '+(checkbox.checked?'enabled.':'disabled; transmissions bypass busy detection.');render(lastStatus);}
            catch(error){checkbox.checked=lastStatus?.transmit?.settings?.wait_for_clear_channel!==false;showTxNotice(error.message);}
            finally{checkbox.disabled=false;}
        };
        $('modem-tx-ptt').onchange=()=>{$('modem-tx-port').disabled=$('modem-tx-ptt').value==='vox';};
        function showTxNotice(message){txNotice=message;if(lastStatus)render(lastStatus);else $('modem-tx-state').textContent=message;}
        $('modem-tx-refresh').onclick=()=>refreshTransmit().catch(error=>showTxNotice(error.message));
        $('modem-tx-apply').onclick=async()=>{
            const button=$('modem-tx-apply');button.disabled=true;txNotice='';
            try {
                if($('modem-tx-enabled').checked && !$('modem-tx-device').value)throw new Error('Choose the radio audio output.');
                const data=await api('transmit-settings',{enabled:$('modem-tx-enabled').checked,
                    device:Number($('modem-tx-device').value),channel:Number($('modem-tx-channel').value),
                    ptt:$('modem-tx-ptt').value,port:$('modem-tx-port').value,gain:Number($('modem-tx-gain').value),
                    delay_ms:Number($('modem-tx-delay').value),tail_ms:Number($('modem-tx-tail').value),wait_for_clear_channel:$('modem-tx-wait-clear').checked});
                render(data);
            }catch(error){showTxNotice(error.message);}
            finally{button.disabled=false;}
        };
        async function disableTransmit(){
            try{txNotice='Transmission disabled.';render(await api('stop-transmit',{}));$('modem-tx-enabled').checked=false;}
            catch(error){showTxNotice(error.message);}
        }
        $('modem-tx-stop').onclick=disableTransmit;
        $('modem-tx-emergency').onclick=disableTransmit;
        $('modem-tx-test').onclick=async()=>{
            txRequestPending=true;showTxNotice(lastStatus?.transmit?.settings?.wait_for_clear_channel===false?'Sending test packet (channel wait disabled)...':'Waiting for channel / sending test packet...');
            try{const result=await api('transmit-test',{});showTxNotice(result.message);}
            catch(error){showTxNotice(error.message);}
            finally{txRequestPending=false;await status();}
        };
        $('modem-close').onclick=()=>dialog.close();
        dialog.addEventListener('close',()=>clearInterval(poll));
        $('modem-decode').onclick=async()=>{
            const file=$('modem-wav').files[0];
            if(!file){$('modem-results').textContent='Choose a PCM WAV recording first.';return;}
            if(file.size>32*1024*1024){$('modem-results').textContent='Choose a recording smaller than 32 MB.';return;}
            $('modem-decode').disabled=true;$('modem-results').textContent='Decoding recording...';
            try{
                const response=await fetch('/api/modem/decode-wav?channel='+$('modem-channel').value,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});
                const data=await response.json();if(!response.ok)throw new Error(data.message||'Could not decode recording.');
                $('modem-results').textContent=`${data.decoded_frames} packets | ${data.audio_seconds.toFixed(2)} s audio | ${data.processing_seconds.toFixed(3)} s processing\n`+data.packets.join('\n');
            }catch(error){$('modem-results').textContent=error.message;}
            finally{$('modem-decode').disabled=false;}
        };
    });
})();

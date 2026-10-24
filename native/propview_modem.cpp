// Original PropView 1200-baud Bell 202 decoder. Apache-2.0.
// Written from public AX.25 framing conventions and quadrature energy detection.
// No GrayWolf, Dire Wolf or other modem implementation source is incorporated.
#include <cmath>
#include <cstdint>
#include <vector>
#include <algorithm>
#include <array>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
using FrameCallback = void (*)(const uint8_t*, int, void*);
constexpr double PI = 3.14159265358979323846;
struct Decoder;
struct Lane {
    double threshold, gain, phase=0; bool tone=false, previous=false, initialized=false;
    uint8_t shift=0; bool collecting=false; std::vector<uint8_t> bits;
    Lane(double t, double g):threshold(t),gain(g) { bits.reserve(4096); }
    void bit(bool value, Decoder& decoder);
    void sample(double discriminator, double step, Decoder& decoder) {
        bool current=discriminator > threshold;
        if (!initialized) {tone=previous=current;initialized=true;}
        if (current!=tone) {
            double error=phase > .5 ? phase-1 : phase;
            phase-=gain*error;
            if(phase<0) phase+=1;
            tone=current;
        }
        double old=phase; phase+=step;
        if(old<.5 && phase>=.5) { bit(current==previous,decoder);previous=current; }
        if(phase>=1) phase-=1;
    }
};
struct Decoder {
    int rate, window, cursor=0; uint64_t samples=0, accepted=0, rejected=0;
    std::vector<std::array<double,4>> ring;
    std::array<double,4> sum={0,0,0,0};
    double mark=0,space=0,step_mark,step_space;
    double peak=0,rms=0; uint64_t clips=0,last_carrier=0; int carrier_score=0;
    std::vector<double> energy_ring; double energy_sum=0;
    std::vector<Lane> lanes;
    std::vector<uint8_t> last_frame; uint64_t last_sample=0;
    FrameCallback callback; void* opaque;
    Decoder(int r, FrameCallback cb, void* arg):rate(r),window(int(std::round(r/1200.0))),
      ring(window),energy_ring(window),step_mark(2*PI*1200/r),step_space(2*PI*2200/r),callback(cb),opaque(arg) {
        lanes.emplace_back(0,.18);lanes.emplace_back(.12,.18);lanes.emplace_back(-.12,.18);
        lanes.emplace_back(0,.08);
    }
    void frame(const std::vector<uint8_t>& bits) {
        std::vector<uint8_t> bytes; bytes.reserve(512);
        unsigned byte=0, pos=0, ones=0;
        for(uint8_t bit:bits) {
            if(bit) { if(++ones>5) return; }
            else { if(ones==5) {ones=0;continue;} ones=0; }
            byte |= unsigned(bit)<<pos;
            if(++pos==8) {bytes.push_back(uint8_t(byte));byte=0;pos=0;}
        }
        if(pos || bytes.size()<18 || bytes.size()>2048) return;
        uint16_t crc=0xffff;
        for(uint8_t byte:bytes) {
            crc^=byte;
            for(int j=0;j<8;j++) crc=(crc&1)? uint16_t((crc>>1)^0x8408):uint16_t(crc>>1);
        }
        if(crc!=0xf0b8) {++rejected;return;}
        bytes.resize(bytes.size()-2);
        if(bytes==last_frame && samples-last_sample<uint64_t(rate/20)) return;
        last_frame=bytes;last_sample=samples;++accepted;
        callback(bytes.data(),int(bytes.size()),opaque);
    }
    void push(const float* input, int frames, int stride, int channel) {
        double squares=0;peak=0;
        for(int i=0;i<frames;i++) {
            double x=input[i*stride+channel];
            if(!std::isfinite(x)) x=0;
            peak=std::max(peak,std::abs(x));squares+=x*x;if(std::abs(x)>=.99)++clips;
            std::array<double,4> v={x*std::cos(mark),x*std::sin(mark),x*std::cos(space),x*std::sin(space)};
            for(int j=0;j<4;j++){sum[j]+=v[j]-ring[cursor][j];ring[cursor][j]=v[j];}
            energy_sum+=x*x-energy_ring[cursor];energy_ring[cursor]=x*x;
            if(++cursor==window)cursor=0;
            mark+=step_mark;space+=step_space;if(mark>=2*PI)mark-=2*PI;if(space>=2*PI)space-=2*PI;
            ++samples;
            double m=sum[0]*sum[0]+sum[1]*sum[1],s=sum[2]*sum[2]+sum[3]*sum[3];
            bool tone_present=energy_sum/window>1e-5 && (m+s)/(window*energy_sum+1e-20)>std::max(.22,2.0/window+.12);
            // A noise impulse must not restart the 200 ms carrier hang timer.
            // Require sustained tone evidence, allowing brief symbol transitions.
            carrier_score=std::clamp(carrier_score+(tone_present?1:-3),0,rate/50);
            if(carrier_score>=rate/125) last_carrier=samples;
            double d=(m-s)/(m+s+1e-16);
            for(auto& lane:lanes)lane.sample(d,1200.0/rate,*this);
        }
        rms=frames?std::sqrt(squares/frames):0;
    }
};
void Lane::bit(bool value, Decoder& decoder) {
    shift=uint8_t((shift>>1)|(value?0x80:0));
    if(collecting)bits.push_back(value);
    if(shift==0x7e) {
        if(collecting && bits.size()>=8){bits.resize(bits.size()-8);decoder.frame(bits);}
        collecting=true;bits.clear();
    } else if(bits.size()>18000) {collecting=false;bits.clear();}
}
API void* pv_create(int rate, FrameCallback callback, void* opaque) {
    if(rate<8000 || rate>192000 || !callback)return nullptr;
    try{return new Decoder(rate,callback,opaque);}catch(...){return nullptr;}
}
API void pv_destroy(void* ptr){delete static_cast<Decoder*>(ptr);}
API void pv_push(void* ptr,const float* samples,int frames,int stride,int channel){
    if(ptr && samples && frames>0 && stride>0 && channel>=0 && channel<stride)
      static_cast<Decoder*>(ptr)->push(samples,frames,stride,channel);
}
API void pv_stats(void* ptr,double* values){
    auto* d=static_cast<Decoder*>(ptr);if(!d||!values)return;
    values[0]=double(d->samples);values[1]=double(d->accepted);values[2]=double(d->rejected);
    values[3]=d->peak;values[4]=d->rms;values[5]=double(d->clips);
    values[6]=(d->last_carrier && d->samples-d->last_carrier<uint64_t(d->rate/5))?1:0;
}

// Bell 202 transmitter: AX.25 FCS, HDLC stuffing, NRZI and continuous-phase AFSK.
// Passing a null output buffer queries the exact required sample count.
API int pv_encode(const uint8_t* frame,int length,int rate,float gain,int delay_ms,int tail_ms,float* output,int capacity) {
    if(!frame || length<16 || length>512 || rate<8000 || rate>96000 || gain<=0 || gain>.9f || delay_ms<50 || delay_ms>1500 || tail_ms<0 || tail_ms>500)return -1;
    std::vector<uint8_t> data(frame,frame+length),bits;
    uint16_t crc=0xffff;
    for(uint8_t byte:data){crc^=byte;for(int i=0;i<8;i++)crc=(crc&1)?uint16_t((crc>>1)^0x8408):uint16_t(crc>>1);}
    crc=uint16_t(~crc);data.push_back(uint8_t(crc));data.push_back(uint8_t(crc>>8));
    auto flag=[&](){for(int i=0;i<8;i++)bits.push_back((0x7e>>i)&1);};
    for(int i=0;i<std::max(2,(delay_ms*1200+7999)/8000);i++)flag();
    unsigned ones=0;
    for(uint8_t byte:data)for(int i=0;i<8;i++){
        bool bit=(byte>>i)&1;bits.push_back(bit);ones=bit?ones+1:0;
        if(ones==5){bits.push_back(0);ones=0;}
    }
    for(int i=0;i<std::max(2,(tail_ms*1200+7999)/8000);i++)flag();
    int required=int((uint64_t(bits.size())*rate+1199)/1200);
    if(!output)return required;
    if(capacity<required)return -1;
    int position=0;bool tone=false;double phase=0;
    for(size_t i=0;i<bits.size();i++){
        if(!bits[i])tone=!tone;
        int end=int((uint64_t(i+1)*rate+1199)/1200);double step=2*PI*(tone?1200:2200)/rate;
        while(position<end){output[position++]=gain*float(std::sin(phase));phase+=step;if(phase>=2*PI)phase-=2*PI;}
    }
    return required;
}
API void pv_resync(void* ptr){
    auto* d=static_cast<Decoder*>(ptr);if(!d)return;
    d->lanes.clear();d->lanes.emplace_back(0,.18);d->lanes.emplace_back(.12,.18);d->lanes.emplace_back(-.12,.18);d->lanes.emplace_back(0,.08);
    for(auto& item:d->ring)item={0,0,0,0};
    std::fill(d->energy_ring.begin(),d->energy_ring.end(),0);d->energy_sum=0;d->sum={0,0,0,0};d->cursor=0;d->last_carrier=0;d->carrier_score=0;
}

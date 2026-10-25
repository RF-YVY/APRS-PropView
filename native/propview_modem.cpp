// PropView enhanced Bell 202 receiver. Original C++17 implementation, Apache-2.0.
// 132 decision/timing lanes; one receive engine, no reference decoder or bit repair.
#include <cmath>
#include <cstdint>
#include <vector>
#include <algorithm>
#include <array>
#include <deque>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C" __attribute__((visibility("default")))
#endif
using FrameCallback = void (*)(const uint8_t*, int, void*);
constexpr double PI=3.14159265358979323846;
struct Experiment;
struct TimingLane {
    double threshold, gain, phase=0, speed=1;
    bool tone=false, previous=false, initialized=false, track;
    uint8_t shift=0; bool collecting=false;
    std::vector<uint8_t> bits;
    TimingLane(double t,double g,bool a):threshold(t),gain(g),track(a){bits.reserve(4096);}
    void sample(double discriminator,double step,Experiment& owner);
};
struct FilterBank {
    int width, cursor=0;
    double cm=1,sm=0,cs=1,ss=0,rmc,rms,rsc,rss;
    double dc=0,previous=0,low=0, low_alpha, tone_power=0;
    int shaping;
    std::array<double,4> sum={};
    std::vector<std::array<double,4>> ring;
    std::vector<TimingLane> lanes;
    FilterBank(int rate,double symbols,double offset,int shape):
        width(std::max(4,int(std::round(rate*symbols/1200)))),shaping(shape),ring(width) {
        double a=2*PI*(1200+offset)/rate,b=2*PI*(2200+offset)/rate;
        rmc=std::cos(a);rms=std::sin(a);rsc=std::cos(b);rss=std::sin(b);
        low_alpha=1-std::exp(-2*PI*1800/rate);
        for(double threshold:{-.60,-.48,-.36,-.18,0.,.18,.36,.48,.60})lanes.emplace_back(threshold,.18,true);
        lanes.emplace_back(0,.07,true);lanes.emplace_back(0,.30,true);
        lanes.emplace_back(0,.18,false);
    }
    double process(double input,int rate) {
        // Remove DC; parallel pre/de-emphasis hypotheses avoid assuming one radio response.
        dc += .002*(input-dc);double x=input-dc;
        low += low_alpha*(x-low);
        if(shaping==1)x=low;
        if(shaping==2){double y=x-.85*previous;previous=x;x=y;}
        std::array<double,4> v={x*cm,x*sm,x*cs,x*ss};
        for(int j=0;j<4;j++){sum[j]+=v[j]-ring[cursor][j];ring[cursor][j]=v[j];}
        if(++cursor==width)cursor=0;
        double t=cm*rmc-sm*rms;sm=sm*rmc+cm*rms;cm=t;
        t=cs*rsc-ss*rss;ss=ss*rsc+cs*rss;cs=t;
        double m=sum[0]*sum[0]+sum[1]*sum[1],s=sum[2]*sum[2]+sum[3]*sum[3];
        tone_power=m+s;
        return (m-s)/(m+s+1e-20);
    }
};
struct Experiment {
    int rate, energy_cursor=0, carrier_score=0;
    double energy_sum=0; std::vector<double> energy_ring; uint64_t last_carrier=0;
    uint64_t samples=0,accepted=0,rejected=0,clips=0;
    double peak=0,rms=0;
    std::vector<FilterBank> banks;
    struct Seen {std::vector<uint8_t> frame;uint64_t sample;};
    std::deque<Seen> seen;
    FrameCallback callback;void* opaque;
    Experiment(int r,FrameCallback cb,void* ctx):rate(r),energy_ring(std::max(4,int(std::round(r/1200.)))),callback(cb),opaque(ctx){reset();}
    void reset(){
        banks.clear();
        for(double offset:{-100.,0.,100.})for(double window:{.70,1.,1.30})banks.emplace_back(rate,window,offset,0);
        banks.emplace_back(rate,1.,0,1);banks.emplace_back(rate,1.,0,2);
        std::fill(energy_ring.begin(),energy_ring.end(),0);energy_sum=0;energy_cursor=0;
        seen.clear();last_carrier=0;carrier_score=0;
    }
    static bool unpack(const std::vector<uint8_t>& bits,std::vector<uint8_t>& bytes) {
        bytes.clear();unsigned value=0,pos=0,ones=0;
        for(auto bit:bits){
            if(bit){if(++ones>5)return false;}
            else{if(ones==5){ones=0;continue;}ones=0;}
            value|=unsigned(bit)<<pos;
            if(++pos==8){bytes.push_back(uint8_t(value));value=0;pos=0;}
        }
        if(pos||bytes.size()<18||bytes.size()>2048)return false;
        uint16_t crc=0xffff;
        for(auto byte:bytes){crc^=byte;for(int j=0;j<8;j++)crc=(crc&1)?uint16_t((crc>>1)^0x8408):uint16_t(crc>>1);}
        if(crc!=0xf0b8)return false;
        bytes.resize(bytes.size()-2);
        // Strict AX.25 address structure and APRS UI/PID checks limit false accepts.
        size_t p=0;int addresses=0;
        while(p+7<=bytes.size() && addresses<10){
            bool nonblank=false;
            for(int j=0;j<6;j++){
                uint8_t c=bytes[p+j]>>1;
                if(bytes[p+j]&1 || !(c==' '||(c>='A'&&c<='Z')||(c>='0'&&c<='9')))return false;
                nonblank|=c!=' ';
            }
            if(!nonblank)return false;
            bool end=bytes[p+6]&1;p+=7;++addresses;
            if(end)return addresses>=2 && p+2<=bytes.size() && bytes[p]==3 && bytes[p+1]==0xf0;
        }
        return false;
    }
    void frame(const std::vector<uint8_t>& bits) {
        std::vector<uint8_t> bytes;
        if(!unpack(bits,bytes)){++rejected;return;}
        while(!seen.empty()&&samples-seen.front().sample>uint64_t(rate/8))seen.pop_front();
        for(const auto& item:seen)if(item.frame==bytes)return;
        seen.push_back({bytes,samples});++accepted;
        callback(bytes.data(),int(bytes.size()),opaque);
    }
    void push(const float* input,int frames,int stride,int channel) {
        double squares=0;peak=0;
        for(int i=0;i<frames;i++){
            double x=input[i*stride+channel];if(!std::isfinite(x))x=0;
            peak=std::max(peak,std::abs(x));squares+=x*x;if(std::abs(x)>=.99)++clips;++samples;
            for(auto& bank:banks){double d=bank.process(x,rate);for(auto& lane:bank.lanes)lane.sample(d,1200./rate,*this);}
            energy_sum+=x*x-energy_ring[energy_cursor];energy_ring[energy_cursor]=x*x;
            if(++energy_cursor==int(energy_ring.size()))energy_cursor=0;
            double width=double(energy_ring.size());
            bool present=energy_sum/width>1e-5 && banks[4].tone_power/(width*energy_sum+1e-20)>std::max(.22,2.0/width+.12);
            carrier_score=std::clamp(carrier_score+(present?1:-3),0,rate/50);
            if(carrier_score>=rate/125)last_carrier=samples;
            // Bound oscillator roundoff on long-running sessions.
            if(samples%uint64_t(rate)==0)for(auto& bank:banks){double m=std::hypot(bank.cm,bank.sm),s=std::hypot(bank.cs,bank.ss);bank.cm/=m;bank.sm/=m;bank.cs/=s;bank.ss/=s;}
        }
        rms=frames?std::sqrt(squares/frames):0;
    }
};
void TimingLane::sample(double d,double step,Experiment& owner){
    bool current=d>threshold;
    if(!initialized){tone=previous=current;initialized=true;}
    if(current!=tone){
        double error=phase>.5?phase-1:phase;
        phase-=gain*error;
        if(track)speed=std::clamp(speed-.0006*error,.97,1.03);
        if(phase<0)phase+=1;tone=current;
    }
    double old=phase;phase+=step*speed;
    if(old<.5&&phase>=.5){
        bool value=current==previous;previous=current;
        shift=uint8_t((shift>>1)|(value?0x80:0));
        if(collecting){bits.push_back(value);}
        if(shift==0x7e){
            if(collecting&&bits.size()>=8){bits.resize(bits.size()-8);owner.frame(bits);}
            collecting=true;bits.clear();
        }else if(bits.size()>18000){collecting=false;bits.clear();}

    }
    if(phase>=1)phase-=1;
}
API void* pv_create(int rate,FrameCallback callback,void* opaque){
    if(rate<8000||rate>192000||!callback)return nullptr;
    try{return new Experiment(rate,callback,opaque);}catch(...){return nullptr;}
}
API void pv_destroy(void* ptr){delete static_cast<Experiment*>(ptr);}
API void pv_push(void* ptr,const float* samples,int frames,int stride,int channel){
    if(ptr&&samples&&frames>0&&stride>0&&channel>=0&&channel<stride)static_cast<Experiment*>(ptr)->push(samples,frames,stride,channel);
}
API void pv_stats(void* ptr,double* values){
    auto* d=static_cast<Experiment*>(ptr);if(!d||!values)return;
    values[0]=double(d->samples);values[1]=double(d->accepted);values[2]=double(d->rejected);
    values[3]=d->peak;values[4]=d->rms;values[5]=double(d->clips);
    values[6]=(d->last_carrier&&d->samples-d->last_carrier<uint64_t(d->rate/5))?1:0;
}
API void pv_resync(void* ptr){if(ptr)static_cast<Experiment*>(ptr)->reset();}

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

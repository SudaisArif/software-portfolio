#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <random>
#include <vector>

using std::vector;

struct Answer { double value; vector<int> order; };

Answer solve(const vector<double>& a) {
  const int n=a.size(), m=n-1, total=1<<m;
  const double neg=-std::numeric_limits<double>::infinity();
  vector<double> dp((size_t)total*m,neg);
  vector<int8_t> par((size_t)total*m,-1);
  auto w=[&](int i,int j){return std::sin(a[j]-a[i]);};
  for(int j=1;j<n;++j) dp[((1<<(j-1))*m)+(j-1)]=w(0,j);
  for(int mask=1;mask<total;++mask) for(int jj=0;jj<m;++jj) {
    int bit=1<<jj; if(!(mask&bit)||mask==bit) continue;
    int pm=mask^bit; double best=neg; int bk=-1;
    for(int kk=0;kk<m;++kk) if(pm&(1<<kk)) {
      double z=dp[(size_t)pm*m+kk]+w(kk+1,jj+1);
      if(z>best){best=z;bk=kk;}
    }
    dp[(size_t)mask*m+jj]=best; par[(size_t)mask*m+jj]=bk;
  }
  int mask=total-1,last=-1; double best=neg;
  for(int j=0;j<m;++j){double z=dp[(size_t)mask*m+j]+w(j+1,0);if(z>best){best=z;last=j;}}
  vector<int> rev;
  while(last>=0){rev.push_back(last+1);int old=last;last=par[(size_t)mask*m+old];mask^=1<<old;}
  std::reverse(rev.begin(),rev.end()); vector<int> order{0};
  order.insert(order.end(),rev.begin(),rev.end()); return {best,order};
}

vector<int> successor(const vector<int>& order){
  vector<int>s(order.size());for(size_t i=0;i<order.size();++i)s[order[i]]=order[(i+1)%order.size()];return s;
}

bool separable(const vector<int>& s){
  int n=s.size();
  for(int cut=0;cut<n;++cut){int mv=-1,mp=n;
    for(int oi=0;oi<n;++oi){int i=(oi-cut+n)%n,j=(s[oi]-cut+n)%n;
      if(i>j){mv=std::max(mv,j);mp=std::min(mp,i);}
    }
    if(mv<mp)return true;
  }return false;
}

double advance(double x,double y){double d=y-x;if(d<=0)d+=2*M_PI;return d;}

bool diameter_separable(const vector<double>& a,const vector<int>& order){
  vector<double> breaks;
  for(double x:a){breaks.push_back(x);x-=M_PI;if(x<0)x+=2*M_PI;breaks.push_back(x);}
  std::sort(breaks.begin(),breaks.end());int n=order.size();
  for(size_t z=0;z<breaks.size();++z){double lo=breaks[z],hi=z+1<breaks.size()?breaks[z+1]:breaks[0]+2*M_PI;
    double x=std::fmod((lo+hi)/2,2*M_PI),y=std::fmod(x+M_PI,2*M_PI);bool ok=true;
    for(int i=0;i<n;++i){int u=order[i],v=order[(i+1)%n];double len=advance(a[u],a[v]);
      bool cx=advance(a[u],x)<len,cy=advance(a[u],y)<len;if(cx&&cy){ok=false;break;}}
    if(ok)return true;
  }return false;
}

int main(int argc,char**argv){
  int n=argc>1?std::stoi(argv[1]):12,trials=argc>2?std::stoi(argv[2]):10000;
  uint64_t seed=argc>3?std::stoull(argv[3]):20260904;
  std::mt19937_64 rng(seed);std::uniform_real_distribution<double> U(0,1);
  int maxneg=0;
  for(int trial=0;trial<trials;++trial){
    double alpha;
    switch(trial%5){case 0:alpha=.3;break;case 1:alpha=.6;break;case 2:alpha=1;break;case 3:alpha=3;break;default:alpha=20;}
    std::gamma_distribution<double> G(alpha,1);
    vector<double> gaps(n);double sum=0;
    for(double&g:gaps){g=G(rng);sum+=g;}
    vector<double>a(n);a[0]=0;
    for(int i=1;i<n;++i)a[i]=a[i-1]+2*M_PI*gaps[i-1]/sum;
    auto ans=solve(a);int negs=0;bool local=true;
    for(int i=0;i<n;++i){double d=advance(a[ans.order[i]],a[ans.order[(i+1)%n]]);if(d>M_PI+1e-10)++negs;
      double e=advance(a[ans.order[(i+1)%n]],a[ans.order[(i+2)%n]]);if(d+e>=2*M_PI+1e-9)local=false;}
    double mingap=2*M_PI-(a.back()-a.front());
    for(int i=1;i<n;++i)mingap=std::min(mingap,a[i]-a[i-1]);
    auto s=successor(ans.order);bool sep=separable(s),dsep=diameter_separable(a,ans.order);maxneg=std::max(maxneg,negs);
    if(!dsep){
      std::cout<<"diameter "<<dsep<<" ";
      std::cout<<"FOUND n "<<n<<" trial "<<trial<<" value "<<ans.value<<" neg "<<negs<<" sep "<<sep<<" local "<<local<<"\nangles";
      for(double x:a)std::cout<<" "<<x;std::cout<<"\norder";for(int x:ans.order)std::cout<<" "<<x;std::cout<<"\n";return 0;
    }
    if((trial+1)%1000==0)std::cerr<<"passed "<<trial+1<<" maxneg "<<maxneg<<"\n";
  }
  std::cout<<"PASS "<<trials<<" maxneg "<<maxneg<<" seed "<<seed<<"\n";
}

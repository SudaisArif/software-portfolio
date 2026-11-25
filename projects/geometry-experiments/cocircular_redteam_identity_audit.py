"""Independent exact checks of the dyadic proof's vulnerable identities."""
from fractions import Fraction as F
from itertools import permutations

if not __debug__:
    raise SystemExit("Run without -O or -OO; this checker requires assertions.")

def K(x,y):return x*y*(y-x)

cases=0
for k in range(2,7):
    G=100*k*k;A=10**8
    for c in (1,2,4):
        # Missing labels simulate a level whose active paths are a subset.
        labels=tuple(2*i for i in range(k))
        xs=tuple(c*(2*A+G*i) for i in labels)
        for prescribed in range(k):
            dom=tuple(i for i in range(k) if i!=prescribed)
            for actual in range(k):
                image=tuple(i for i in range(k) if i!=actual)
                for perm in permutations(image):
                    deltas=tuple(xs[j]-xs[i] for i,j in zip(dom,perm))
                    assert sum(deltas)==xs[prescribed]-xs[actual]
                    for valley in (0,k-1):
                        gain=sum(K(xs[i],2*xs[i])-K(xs[j],2*xs[i])
                                 for i,j in zip(dom,perm))
                        gain+=K(xs[prescribed],valley)-K(xs[actual],valley)
                        formula=sum(2*xs[i]*d*d+valley*(valley-xs[prescribed]-xs[actual])*d
                                    for i,d in zip(dom,deltas))
                        assert gain==formula
                        assert gain>=2*c*A*G*sum(map(abs,deltas))
                        if any(deltas):assert gain>=2*A*G*G
                        cases+=1
assert cases == 30228
print('PASS: micro correction identity and gap on',cases,'exact assignments')

count=0
for k in range(2,8):
    A=k**4+1
    for tau in permutations(range(k)):
        baseline=sum(K(i,A+i) for i in range(k))
        actual=sum(K(i,A+tau[i]) for i in range(k))
        displacement=sum(i*(i-tau[i]) for i in range(k))
        correction=sum(i*tau[i]*(tau[i]-i) for i in range(k))
        assert baseline-actual==2*A*displacement-correction
        assert abs(correction)<k**4
        assert baseline-actual>=0
        count+=1
assert count == 5912
print('PASS: initial-block loss formula and nonnegativity for',count,'permutations')

circle_pairs=0
nonnegative_pairs=0
for B in range(1,12):
    n=7;eps=F(1,8*n*B**3)
    def q(x):
        t=eps*x
        return ((1-t*t)/(1+t*t),2*t/(1+t*t))
    for x in range(-B,B+1):
        for y in range(-B,B+1):
            a,b=q(x),q(y)
            determinant=a[0]*b[1]-a[1]*b[0]
            translated=(a[0]-1)*b[1]-a[1]*(b[0]-1)
            denominator=(1+eps**2*x*x)*(1+eps**2*y*y)
            assert translated == 4*eps**3*K(x,y)/denominator
            if x>=0 and y>=0:
                assert abs(translated/(4*eps**3)-K(x,y))<=2*eps**2*B**5
                nonnegative_pairs+=1
            polynomial=2*eps*(y-x)+2*eps**3*(x**3-y**3)+4*eps**3*K(x,y)
            assert abs(determinant-polynomial)<=40*eps**5*B**5
            circle_pairs+=1
    assert 40*n*eps**5*B**5<2*eps**3
    assert 2*n*eps**2*B**5 == F(1,32*n*B) < F(1,2)
assert circle_pairs == 2299
assert nonnegative_pairs == 649
print('PASS: exact translated-circle identity and Taylor bound on',circle_pairs,'integer pairs')
print('PASS: normalized circle error on',nonnegative_pairs,'nonnegative pairs and 11 total gap bounds')

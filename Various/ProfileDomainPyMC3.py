import numpy as np
import matplotlib.pyplot as plt
import numpy as np
import psrchive
from libstempo.libstempo import *
import libstempo as T


import numpy
import theano
import theano.tensor as tt
from theano import pp


theano.config.compute_test_value='off'


#parameters that define a two gaussian model
gsep    = Savex[1]*ReferencePeriod/1024
g1width = Savex[2]*ReferencePeriod/1024
g2width = Savex[3]*ReferencePeriod/1024
g2amp   = Savex[4]


Tg1width=theano.shared(g1width)
Tg2width =theano.shared(g2width)
Tg2amp=theano.shared(g2amp)
Tgsep=theano.shared(gsep)


amps   = tt.dvector('amps')
offs   = tt.dvector('offs')
sigs   = tt.dvector('sigs')
phase  = tt.dscalar('phase')

x = ( TFlatTimes - phase + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2
y = tt.exp(-0.5*(x)**2/Tg1width**2)
x2 = ( TFlatTimes - phase - gsep + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2
y2 = g2amp*tt.exp(-0.5*(x2)**2/Tg1width**2)


AmpVec = theano.tensor.extra_ops.repeat(amps, 1024)
OffVec = theano.tensor.extra_ops.repeat(offs, 1024)
SigVec = theano.tensor.extra_ops.repeat(sigs, 1024)

Nbins=Nbins.astype(int)
TNbins=theano.shared(Nbins)

s = AmpVec*(y+y2) + OffVec

like = -0.5*tt.sum(((FlatData-s)/SigVec)**2) -0.5*tt.sum(TNbins[:useToAs]*tt.log(sigs**2))

glike = tt.grad(like, [phase, amps, offs, sigs])

getS = theano.function([phase, amps, offs], s)
getX = theano.function([phase, amps, offs, sigs], like)	
getG = theano.function([phase, amps, offs, sigs], glike)


def TheanoFunc2(phaseval, ampvec, offvec, sigvec):


	return getX(phaseval, ampvec, offvec, sigvec), getG(phaseval, ampvec, offvec, sigvec)#, getS(phaseval, ampvec, offvec)


start = time.clock()
ltot = 0
for i in range(20000):
	if(i%100 == 0):
		print i

	pval = 0.00288206
	avals = np.random.normal(0,1,useToAs)
	ovals = np.random.normal(0,1,useToAs)
	nvals = np.random.normal(0,1,useToAs)**2
	
	l, g = TheanoFunc2(pval, avals, ovals, nvals)

	ltot += l

end = time.clock()

#Function returns matrix containing interpolated shapelet basis vectors given a time 'interpTime' in ns, and a Beta value to use.
def PreComputeShapelets(interpTime = 1, MeanBeta = 1):


	print("Calculating Shapelet Interpolation Matrix : ", interpTime, MeanBeta);

	'''
	/////////////////////////////////////////////////////////////////////////////////////////////  
	/////////////////////////Profile Params//////////////////////////////////////////////////////
	/////////////////////////////////////////////////////////////////////////////////////////////
	'''

	numtointerpolate = np.int(ReferencePeriod/1024/interpTime/10.0**-9)+1
	InterpolatedTime = ReferencePeriod/1024/numtointerpolate

	InterpShapeMatrix = []
	MeanBeta = MeanBeta/1024*ReferencePeriod

	InterpBins = 1024
	interpStep = ReferencePeriod/InterpBins/numtointerpolate
	
	

	for t in range(numtointerpolate):


		binpos = t*interpStep

		samplerate = ReferencePeriod/InterpBins
		x = np.linspace(binpos, binpos+samplerate*(InterpBins-1), InterpBins)
		x = ( x + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2
		x=x/MeanBeta

		hermiteMatrix = np.zeros([InterpBins, MaxCoeff])
		for i in range(MaxCoeff):
			amps = np.zeros(MaxCoeff)
			amps[i] = 1
			s = numpy.polynomial.hermite.hermval(x, amps)*np.exp(-0.5*(x)**2)
			hermiteMatrix[:,i] = s
		InterpShapeMatrix.append(np.copy(hermiteMatrix))

	
	InterpShapeMatrix = np.array(InterpShapeMatrix)
	print("Finished Computing Interpolated Profiles")
	return InterpShapeMatrix, InterpolatedTime




#Funtion to determine an estimate of the white noise in the profile data
def GetProfNoise(profamps):

	Nbins = len(profamps)
	Step=100
	noiselist=[]
	for i in range(Nbins-Step):
		noise=np.std(profamps[i:i+Step])
		noiselist.append(noise)
	noiselist=np.array(noiselist)
	minnoise=np.min(noiselist)
	threesiglist=noiselist[noiselist<3*minnoise]
	mediannoise=np.median(threesiglist)
	return mediannoise

SECDAY = 24*60*60

#First load pulsar.  We need the sats (separate day/second), and the file names of the archives (FNames)
psr = T.tempopulsar(parfile="OneChan.par", timfile = "OneChan.tim")
psr.fit()
SatSecs = psr.satSec()
SatDays = psr.satDay()
FNames = psr.fnames()
NToAs = psr.nobs


#Check how many timing model parameters we are fitting for (in addition to phase)
numTime=len(psr.pars())
redChisq = psr.chisq()/(psr.nobs-len(psr.pars())-1)
TempoPriors=np.zeros([numTime,2]).astype(np.float64)
for i in range(numTime):
        TempoPriors[i][0]=psr[psr.pars()[i]].val
        TempoPriors[i][1]=psr[psr.pars()[i]].err/np.sqrt(redChisq)
	print "fitting for: ", psr.pars()[i], TempoPriors[i][0], TempoPriors[i][1]


designMatrix=psr.designmatrix(incoffset=False)
for i in range(numTime):
	designMatrix[:,i] *= TempoPriors[i][1]

designMatrix=np.float64(designMatrix)

#Now loop through archives, and work out what subint/frequency channel is associated with a ToA.
#Store whatever meta data is needed (MJD of the bins etc)
#If multiple polarisations are present we first PScrunch.

ProfileData=[]
ProfileMJDs=[]
ProfileInfo=[]


profcount = 0
while(profcount < NToAs):
    arch=psrchive.Archive_load(FNames[profcount])

    
    npol = arch.get_npol()
    if(npol>1):
        arch.pscrunch()

    nsub=arch.get_nsubint()


    for i in range(nsub):
        subint=arch.get_Integration(i)
        
        nbins = subint.get_nbin()
        nchans = subint.get_nchan()
        npols = subint.get_npol()
        foldingperiod = subint.get_folding_period()
        inttime = subint.get_duration()
        centerfreq = subint.get_centre_frequency()
        
        #print "Subint Info:", i, nbins, nchans, npols, foldingperiod, inttime, centerfreq
        
        firstbin = subint.get_epoch()
        intday = firstbin.intday()
        fracday = firstbin.fracday()
        intsec = firstbin.get_secs()
        fracsecs = firstbin.get_fracsec()
        isdedispersed = subint.get_dedispersed()
        
        pulsesamplerate = foldingperiod/nbins/SECDAY;
        
        nfreq=subint.get_nchan()
        
        FirstBinSec = intsec + np.float128(fracsecs)
        SubIntTimeDiff = FirstBinSec-SatSecs[profcount]*SECDAY
        PeriodDiff = SubIntTimeDiff*psr['F0'].val
        
        if(abs(PeriodDiff) < 2.0):
            for j in range(nfreq):
                chanfreq = subint.get_centre_frequency(j)
                toafreq = psr.freqs[profcount]
                prof=subint.get_Profile(0,j)
                profamps = prof.get_amps()
                
                if(np.sum(profamps) != 0 and abs(toafreq-chanfreq) < 0.001):
		    noiselevel=GetProfNoise(profamps)
                    ProfileData.append(np.copy(profamps))
                    ProfileInfo.append([SatSecs[profcount], SatDays[profcount], np.float128(intsec)+np.float128(fracsecs), pulsesamplerate, nbins, foldingperiod, noiselevel])                    
                    #print "ChanInfo:", j, chanfreq, toafreq
                    profcount += 1
                    if(profcount == NToAs):
                        break

len(ProfileData)
ProfileInfo=np.array(ProfileInfo)
ProfileData = np.array(ProfileData)

parameters = []
for i in range(NToAs):
	parameters.append('Amp'+str(i))
for i in range(NToAs):
	parameters.append('BL'+str(i))
for i in range(NToAs):
	parameters.append('Noise'+str(i))

n_params = len(parameters)
print n_params


Savex = np.array(np.zeros(5))

Savex[0] = -6.30581674e-01
Savex[1] = 9.64886554e+01
Savex[2] = 3.12774568e+01
Savex[3] = 2.87192467e+01
Savex[4] = 1.74380328e+00


useToAs=100

toas=psr.toas()
residuals = psr.residuals(removemean=False)
BatCorrs = psr.batCorrs()
ModelBats = psr.satSec() + BatCorrs - residuals/SECDAY

ProfileStartBats = ProfileInfo[:,2]/SECDAY + ProfileInfo[:,3]*0 + ProfileInfo[:,3]*0.5 + BatCorrs
ProfileEndBats =  ProfileInfo[:,2]/SECDAY + ProfileInfo[:,3]*(ProfileInfo[:,4]-1) + ProfileInfo[:,3]*0.5 + BatCorrs

Nbins = ProfileInfo[:,4]
ProfileBinTimes = []
for i in range(NToAs):
	ProfileBinTimes.append((np.linspace(ProfileStartBats[i], ProfileEndBats[i], Nbins[i])-ModelBats[i])*SECDAY)
ShiftedBinTimes = np.float64(np.array(ProfileBinTimes))

FlatBinTimes = (ShiftedBinTimes.flatten())[:useToAs*1024]

ReferencePeriod = np.float64(ProfileInfo[0][5])

#MaxCoeff = 10
#InterpBasis, InterpolatedTime = PreComputeShapelets(interpTime = 1, MeanBeta = 47.9)



from pymc3 import Model, Normal, HalfNormal, Uniform, theano
from theano import tensor as tt
from theano import function


TRP = theano.shared(ReferencePeriod)
TBinTimes = theano.shared(ShiftedBinTimes)
#TInterpBasis  = theano.shared(InterpBasis)
#TInterpolatedTime = theano.shared(InterpolatedTime)

TFlatTimes = theano.shared(FlatBinTimes)
FlatData = (ProfileData.flatten())[:useToAs*1024]




basic_model = Model()

with basic_model:

	# Priors for unknown model parameters
	amplitude = Normal('amplitude', mu=0, sd=10000, shape = useToAs)
	offset = Normal('offset', mu=0, sd=10000, shape = useToAs)
	noise = HalfNormal('noise', sd=10000, shape = useToAs)
	phase = Uniform('phase', lower = 0, upper = ReferencePeriod)


	#parameters that define a two gaussian model
	gsep    = Savex[1]*ReferencePeriod/1024
	g1width = Savex[2]*ReferencePeriod/1024
	g2width = Savex[3]*ReferencePeriod/1024
	g2amp   = Savex[4]


	Tg1width=theano.shared(g1width)
	Tg2width =theano.shared(g2width)
	Tg2amp=theano.shared(g2amp)
	Tgsep=theano.shared(gsep)


	#Calculate the X values for first gaussian, these have to wrap on a period of [-ReferencePeriod/2, ReferencePeriod/2]
	x = TFlatTimes - phase
	x = ( x + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2

	#Calculate the signal values for first gaussian
	FlatS = np.exp(-0.5*(x)**2/Tg1width**2)


	#Calculate the X values for second gaussian, these have to wrap on a period of [-ReferencePeriod/2, ReferencePeriod/2]
	x = TFlatTimes-phase-Tgsep
	x = ( x + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2

	#Calculate the signal values for second gaussian
	FlatS  += Tg2amp*np.exp(-0.5*(x)**2/Tg1width**2)



	#Construct total vectors containing offsets, amplitude and noise parameters.
	#Each is (1024*useToAs) in length with the format (A_1, A_1, ...., A_1, A_2, A_2, ..., A_2, ......, A_useToAs, ..A_useToAs)
	NVec = theano.tensor.extra_ops.repeat(noise, 1024)
	Offs = theano.tensor.extra_ops.repeat(offset, 1024)
	Amps = theano.tensor.extra_ops.repeat(amplitude, 1024)


	#combine total signal
	Signal = Offs + Amps*FlatS

	# Likelihood (sampling distribution) of observations
	Y_obs = Normal('Y_obs', mu=Signal, sd=NVec, observed=FlatData)




'''

pval = start.get('phase')
pval = 0.0028798#-0.00626009
offs=start.get('offset')
amps=start.get('amplitude')

ovec = np.repeat(offs, 1024)
avec = np.repeat(amps, 1024)

xvec = FlatBinTimes-pval
xvec = ( xvec + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2

s =  np.exp(-0.5*(xvec)**2/g1width**2)

xvec = FlatBinTimes-pval-gsep
xvec = ( xvec + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2

s += g2amp*np.exp(-0.5*(xvec)**2/g2width**2)

svec = ovec + avec*s


pval2=start.get('phase')
xvec2 = FlatBinTimes-pval2
xvec2 = ( xvec2 + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2
s2 =  np.exp(-0.5*(xvec2)**2/g1width**2)

xvec2 = FlatBinTimes-pval2-gsep
xvec2 = ( xvec + ReferencePeriod/2) % (ReferencePeriod ) - ReferencePeriod/2

s += g2amp*np.exp(-0.5*(xvec)**2/g2width**2)

svec = ovec + avec*s


plt.plot(np.linspace(0,useToAs, 1024*useToAs), FlatData, color='black')
plt.plot(np.linspace(0,useToAs, 1024*useToAs), svec, color='red')
plt.show()

# Likelihood (sampling distribution) of observations
Y_obs += Normal('Y_obs', mu=s, sd=noise[i], observed=ProfileData[i])
'''


def uniformTransform(x, pmin, pmax):
	return np.log((x - pmin) / (pmax - x))

def uniformErrTransform(x, err, pmin, pmax):

	t1 = uniformTransform(x, pmin, pmax)
	t2 = uniformTransform(x+err, pmin, pmax)
	t3 = uniformTransform(x-err, pmin, pmax)

	diff1=t2-t1
	diff2=t1-t3

	return 0.5*(diff1+diff2)




def ML(useToAs):


	ReferencePeriod = ProfileInfo[0][5]
	FoldingPeriodDays = ReferencePeriod/SECDAY
	phase=Savex[0]*ReferencePeriod/SECDAY

	pcount = numTime+1

	phase   = Savex[0]*ReferencePeriod/SECDAY
	gsep    = Savex[1]*ReferencePeriod/SECDAY/1024
	g1width = np.float64(Savex[2]*ReferencePeriod/SECDAY/1024)
	g2width = np.float64(Savex[3]*ReferencePeriod/SECDAY/1024)
	g2amp   = Savex[4]


	toas=psr.toas()
	residuals = psr.residuals(removemean=False)
	BatCorrs = psr.batCorrs()
	ModelBats = psr.satSec() + BatCorrs - phase - residuals/SECDAY


	amplitude=np.zeros(useToAs)
	noise_log_=np.zeros(useToAs)
	offset = np.zeros(useToAs)
	for i in range(useToAs):

		'''Start by working out position in phase of the model arrival time'''

		ProfileStartBat = ProfileInfo[i,2]/SECDAY + ProfileInfo[i,3]*0 + ProfileInfo[i,3]*0.5 + BatCorrs[i]
		ProfileEndBat = ProfileInfo[i,2]/SECDAY + ProfileInfo[i,3]*(ProfileInfo[i,4]-1) + ProfileInfo[i,3]*0.5 + BatCorrs[i]

		Nbins = ProfileInfo[i,4]
		x=np.linspace(ProfileStartBat, ProfileEndBat, Nbins)

		minpos = ModelBats[i] - FoldingPeriodDays/2
		if(minpos < ProfileStartBat):
			minpos=ProfileStartBat

		maxpos = ModelBats[i] + FoldingPeriodDays/2
		if(maxpos > ProfileEndBat):
			maxpos = ProfileEndBat


		'''Need to wrap phase for each of the Gaussian components separately.  Fortran style code incoming'''

		BinTimes = x-ModelBats[i]
		BinTimes[BinTimes > maxpos-ModelBats[i]] = BinTimes[BinTimes > maxpos-ModelBats[i]] - FoldingPeriodDays
		BinTimes[BinTimes < minpos-ModelBats[i]] = BinTimes[BinTimes < minpos-ModelBats[i]] + FoldingPeriodDays

		BinTimes=np.float64(BinTimes)
		    
		s = 1.0*np.exp(-0.5*(BinTimes)**2/g1width**2)


		BinTimes = x-ModelBats[i]-gsep
		BinTimes[BinTimes > maxpos-ModelBats[i]-gsep] = BinTimes[BinTimes > maxpos-ModelBats[i]-gsep] - FoldingPeriodDays
		BinTimes[BinTimes < minpos-ModelBats[i]-gsep] = BinTimes[BinTimes < minpos-ModelBats[i]-gsep] + FoldingPeriodDays

		BinTimes=np.float64(BinTimes)

		s += g2amp*np.exp(-0.5*(BinTimes)**2/g2width**2)

		'''Now subtract mean and scale so std is one.  Makes the matrix stuff stable.'''

		#smean = np.sum(s)/Nbins 
		#s = s-smean

		#sstd = np.dot(s,s)/Nbins
		#s=s/np.sqrt(sstd)

		'''Make design matrix.  Two components: baseline and profile shape.'''

		M=np.ones([2,Nbins])
		M[1] = s


		pnoise = ProfileInfo[i][6]

		MNM = np.dot(M, M.T)      
		MNM /= (pnoise*pnoise)

		'''Invert design matrix. 2x2 so just do it numerically'''


		detMNM = MNM[0][0]*MNM[1][1] - MNM[1][0]*MNM[0][1]
		InvMNM = np.zeros([2,2])
		InvMNM[0][0] = MNM[1][1]/detMNM
		InvMNM[1][1] = MNM[0][0]/detMNM
		InvMNM[0][1] = -1*MNM[0][1]/detMNM
		InvMNM[1][0] = -1*MNM[1][0]/detMNM

		logdetMNM = np.log(detMNM)
		    
		'''Now get dNM and solve for likelihood.'''
		    
		    
		dNM = np.dot(ProfileData[i], M.T)/(pnoise*pnoise)


		dNMMNM = np.dot(dNM.T, InvMNM)

		baseline=dNMMNM[0]
		amp = dNMMNM[1]
		noise = np.std(ProfileData[i] - baseline - amp*s)

		amplitude[i] = amp
		noise_log_[i] = np.log(noise)
		offset[i] = baseline

		#print "ML", amp, baseline, noise

	d = {'amplitude': amplitude, 'noise_log_': noise_log_, 'offset': offset, 'phase_interval_': uniformTransform(0.00288206, 0, ReferencePeriod)}

	return d




def hessian(useToAs):
	pnoise=ProfileInfo[:useToAs,6]**2
	onehess=1.0/np.float64(ProfileInfo[:useToAs,4]/pnoise)
	noisehess = 1.0/(ProfileInfo[:useToAs,4]*(3.0/(ProfileInfo[:useToAs,6]*ProfileInfo[:useToAs,6]) - 1.0/(ProfileInfo[:useToAs,6]*ProfileInfo[:useToAs,6])))
	d = {'amplitude': np.float64(onehess), 'noise_log_': np.float64(noisehess), 'offset': np.float64(onehess), 'phase_interval_': np.ones(1)*uniformErrTransform(0.00288206, 1.0559855345705067e-07,  0, ReferencePeriod)**2}

	return d




'''
from pymc3 import find_MAP

map_estimate = find_MAP(model=basic_model, start=ML(useToAs))

print(map_estimate)

from scipy import optimize

map_estimate = find_MAP(model=basic_model, fmin=optimize.fmin_powell, start=ML(useToAs))

print(map_estimate)
'''


'''
Metropolis Hastings Sampler
'''

MLpoint = ML(useToAs)
hess = hessian(useToAs)



from pymc3 import Metropolis, sample

with basic_model:

	# Use starting ML point
	start = MLpoint

	#hess = hessian(useToAs)

	step1 = Metropolis(vars = [amplitude, offset, noise, phase],  h=np.diag(basic_model.dict_to_array(hess)))

	# draw 2000 posterior samples
	trace = sample(10000, start=start, step=step1)

from pymc3 import traceplot

traceplot(trace);
plt.show()
 

accept = np.float64(np.sum(trace['phase'][1:] != trace['phase'][:-1]))
print "Acceptance Rate: ", accept/trace['phase'].shape[0]


'''
HMC Sampler
'''


from pymc3 import HamiltonianMC, sample

with basic_model:

	# Use starting ML point
	start = MLpoint

	hess = hessian(useToAs)

	step1 = HamiltonianMC(vars = [noise, offset, amplitude, phase], scaling=basic_model.dict_to_array(hess), is_cov=True)

	# draw 2000 posterior samples
	trace = sample(2000, start=start, step=step1, njobs = 1)



accept = np.float64(np.sum(trace['phase'][1:] != trace['phase'][:-1]))
print "Acceptance Rate: ", accept/trace['phase'].shape[0]


from pymc3 import traceplot

traceplot(trace);
plt.show()



'''
NUTS Sampler
'''


from pymc3 import NUTS, sample

with basic_model:

	# Use starting ML point
	start = MLpoint

	hess = hessian(useToAs)

	#Set scaling using hessian
	step = NUTS()
	# draw 2000 posterior samples
	trace = sample(2000, start=start)

from pymc3 import traceplot

traceplot(trace);
plt.show()


accept = np.float64(np.sum(trace['phase'][1:] != trace['phase'][:-1]))
print "Acceptance Rate: ", accept/trace['phase'].shape[0]


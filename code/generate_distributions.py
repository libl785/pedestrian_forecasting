import numpy as np
from scipy import integrate
import itertools
import scipy as sp
from scene import Scene
from functools import partial
import matplotlib.pyplot as plt

from derived_posteriors import prob_k_s_x0_given_mu, _normalizing_constant

def make_generator(scene, x, v, dt, Nt):
    """ Makes a generator from a scene object and an initial condition
    args:
        scene: a scene object
        x: np.array(2)
        v: np.array(2)
        dt: float
        Nt: int
    returns:
        a generator object

        Example:
            g = make_generator(scene, x,v,dt,Nt):
            for data in g:
                for k in range( scene.num_nl_classes ):
                    xy, weights = data[k]
                    #DO STUFF WITH DIRAC DELTAS
                lin_term = data[ scene.num_nl_classes ]
                #DO STUFF WITH LINEAR TERM
    """
    _x, _v = x, v

    def gen(k):
        """ A generator up to time T = Nt * dt"""

        def ode_function(t, state):
            xy = state.reshape((2,len(state)/2))
            return scene.director_field_vectorized(k, xy).flatten()
        ode_forward = integrate.ode(ode_function)
        ode_forward.t = 0.0
        nl_res = 20
        dx = scene.bbox_width / (nl_res-1)
        dvol = dx**2
        x_span = np.linspace(
                x[0]-scene.bbox_width/2.0,
                x[0]+scene.bbox_width/2.0,
                nl_res)
        y_span = np.linspace(
                x[1]-scene.bbox_width/2.0,
                x[1]+scene.bbox_width/2.0,
                nl_res)
        xy = np.vstack(
                [spam.flatten() for spam in np.meshgrid(x_span, y_span)])
        N_points = xy.shape[1]
        initial_condition = xy.flatten()
        ode_forward.set_initial_value(initial_condition)
        ode_forward.set_integrator('dopri5')
        ode_backward = integrate.ode(ode_function)
        ode_backward.t = 0.0
        ode_backward.set_initial_value(initial_condition)
        ode_backward.set_integrator('dopri5')
        xy_arr = np.zeros((2*Nt+1, 2, N_points))
        weight_arr = np.zeros((2*Nt+1, N_points))
        xy_arr[0] = initial_condition.reshape((2, N_points))
        print "Begin advection for " + str(k)
        for n in range(1,Nt):
            ds = scene.s_max / float(n)
            #Compute locations
            ode_forward.integrate(ode_forward.t + dt*scene.s_max)
            assert(ode_forward.successful())
            xy_arr[n] = ode_forward.y.reshape(2, N_points)
            ode_backward.integrate(ode_backward.t - dt*scene.s_max)
            assert(ode_backward.successful())
            xy_arr[-n] = ode_backward.y.reshape(2, N_points)

            #Computes weights
            if n != Nt-1:
                continue
            print "Finished advection for " + str(k)
            for l in range(-n, n+1):
                x_l = xy_arr[l] #TODO hoj:  It appears I forgot to multiply by dx!!!  In fact, I didn't compute |dx| anywhere.
                s_l = l*ds*np.ones( x_l.shape[1] )
                weight_arr[l] = prob_k_s_x0_given_mu(
                        k, s_l, np.transpose(xy_arr[0]), _x, _v)
                weight_arr[l] *= ds * dvol
            #x_out = np.concatenate([xy_arr[-n:], xy_arr[:n+1]], axis=0)
            #weight_out = np.concatenate([weight_arr[-n:], weight_arr[:n+1]],
            #        axis=0)
            print "Finished for " + str(k)
            #weights = weight_arr.flatten()
            #where = np.where(weights > 0)[0]
            #ret_weight = weights[where]
            #xy_xs = xy_arr[:, 0, :].flatten()[where]
            #xy_ys = xy_arr[:, 1, :].flatten()[where]
            #ret_xy = np.array(zip(xy_xs, xy_ys))

            yield xy_arr, weight_arr

    def gen_linear():
        #use scene.sigma_v
        tl = 0.0
        lin_terms = []
        for n in range(Nt):
            tl += dt
            def linear_term(t, xy):
                x,y = xy
                plt.scatter(_x[0], _x[1], s=100)
                sigma = scene.sigma_v
                w, h = scene.width/2.0, scene.height/2.0
                wx = scene.bbox_width/2.0
                wv = scene.bbox_velocity_width/2.0
                def np_max(*args):
                    comp = lambda x,y: x*(x>y)+y*(y>x)
                    return reduce(comp, args[1:], args[0])
                def np_min(*args):
                    comp = lambda x,y: x*(x<y)+y*(y<x)
                    return reduce(comp, args[1:], args[0])
                u_min = np_max((x-w)/t, (x-_x[0]-wx)/t, _v[0] - wv)
                v_min = np_max((y-h)/t, (y-_x[1]-wx)/t, _v[1] - wv)
                u_max = np_max(u_min, np_min((x+w)/t, (x-_x[0]+wx)/t, _v[0] + wv))
                v_max = np_max(v_min, np_min((y+h)/t, (y-_x[1]+wx)/t, _v[1] + wv))
                Prob_of_x_hat_and_v_hat = _normalizing_constant(_x, _v)
                scale = scene.P_of_c[-1] / Prob_of_x_hat_and_v_hat
                scale /= h * w * wx**2 * wv**2
                from scipy.special import erf
                rt2 = np.sqrt(2)
                out = erf( u_max/(sigma*rt2) ) - erf( u_min/(sigma*rt2) )
                out *= erf( v_max/(sigma*rt2) ) - erf( v_min/(sigma*rt2) )
                out *= 0.25 * scale
                return out
            lin_terms.append(partial(linear_term, tl))
            if n != Nt-1:
                continue
            yield lin_terms
    gen_ls = [ gen(k) for k in range(scene.num_nl_classes)]
    gen_ls.append( gen_linear() )
    return itertools.izip(*gen_ls)

if __name__ == '__main__':
    import pickle
    from scene import Scene
    from integrate import trap_quad
    import matplotlib.pyplot as plt
    with open('test_scene.pkl', 'rs') as f:
        scene = pickle.load(f)
    with open('test_set.pkl', 'rs') as f:
        test_set = pickle.load(f)
    dt = 0.1
    Nt = 100
    test_BB_ts = test_set[3]
    def get_initial_condition(BB_ts):
        fd_width = 4
        BB0 = BB_ts[:,0]
        BB2 = BB_ts[::,fd_width]
        x = 0.5*(BB0[0]+BB0[2]+BB2[0]+BB2[2]) / fd_width
        y = 0.5*(BB0[1]+BB0[3]+BB2[1]+BB2[3]) / fd_width
        u = 0.5*(BB2[0]-BB0[0]+BB2[2]-BB0[2]) / fd_width
        v = 0.5*(BB2[1]-BB0[1]+BB2[3]-BB0[3]) / fd_width
        return np.array([x, y]), np.array([u, v])

    x,v = get_initial_condition(test_BB_ts[:, 10:])
    plt.scatter(x[0], x[1], s=60)
    speed = np.sqrt(np.sum(v**2))
    print "Measured speed / sigma_v = {:f}".format( speed / scene.sigma_v )
    print "sigma_v = {:f}".format( scene.sigma_v)
    gen = make_generator(scene, x, v, dt, Nt)
    xy_grid = np.random.randn(2,100)
    for data in gen:
        td_sum = 0
        xs = np.array([])
        ys = np.array([])
        for k in range(scene.num_nl_classes):
            xy, weights = data[k]
            xs = xy[:, 0]
            ys = xy[:, 1]
            print "max_weight = {:f}".format(weights.max())
            td_sum += sum(weights.flatten())
        plt.scatter(xs, ys, color="k")
        plt.show()
        lin_term = data[-1]

        def temp(x, y):
            return lin_term(np.array([x, y]))

        bounds = [-0.5*scene.width, 0.5*scene.width, -0.5*scene.height, 0.5 * scene.height]
        quad = trap_quad(temp, bounds, (200, 200))
        td_sum += quad
        print "Should be 1:"
        print td_sum
        #print lin_term( xy_grid )
